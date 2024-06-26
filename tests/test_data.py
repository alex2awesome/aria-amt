import unittest
import logging
import os
import cProfile
import pstats
import torch
import torchaudio
import matplotlib.pyplot as plt

from amt.data import get_wav_mid_segments, AmtDataset
from amt.tokenizer import AmtTokenizer
from amt.audio import AudioTransform, log_mel_spectrogram
from amt.train import get_dataloaders
from aria.data.midi import MidiDict


logging.basicConfig(level=logging.INFO)
if os.path.isdir("tests/test_results") is False:
    os.mkdir("tests/test_results")

MAESTRO_PATH = "/mnt/ssd1/amt/training_data/train.txt"


def plot_spec(mel: torch.Tensor, name: str | int):
    plt.figure(figsize=(10, 4))
    plt.imshow(mel, aspect="auto", origin="lower", cmap="viridis")
    plt.colorbar(format="%+2.0f dB")
    plt.title("(mel)-Spectrogram")
    plt.tight_layout()
    plt.savefig(f"tests/test_results/{name}.png")
    plt.close()


# Need to test this properly, have issues turning mel_spec back into audio
class TestDataGen(unittest.TestCase):
    def test_wav_mid_segments(self):
        for log_spec, seq in get_wav_mid_segments(
            audio_path="tests/test_data/147.wav",
            mid_path="tests/test_data/147.mid",
        ):
            print(log_spec.shape, len(seq))


class TestAmtDataset(unittest.TestCase):
    def test_build(self):
        matched_paths = [
            ("tests/test_data/maestro.wav", "tests/test_data/maestro1.mid")
            for _ in range(3)
        ]
        if os.path.isfile("tests/test_results/dataset.jsonl"):
            os.remove("tests/test_results/dataset.jsonl")

        AmtDataset.build(
            load_paths=matched_paths,
            save_path="tests/test_results/dataset.jsonl",
        )

        dataset = AmtDataset("tests/test_results/dataset.jsonl")
        tokenizer = AmtTokenizer()
        for idx, (wav, src, tgt, idx) in enumerate(dataset):
            print(wav.shape, src.shape, tgt.shape)
            src_decoded = tokenizer.decode(src)
            tgt_decoded = tokenizer.decode(tgt)
            self.assertListEqual(src_decoded[1:], tgt_decoded[:-1])

            mid = tokenizer._detokenize_midi_dict(
                src_decoded, len_ms=30000
            ).to_midi()
            mid.save(f"tests/test_results/trunc_{idx}.mid")

    def test_maestro(self):
        if not os.path.isfile(MAESTRO_PATH):
            return

        tokenizer = AmtTokenizer()
        audio_transform = AudioTransform()
        dataset = AmtDataset(load_path=MAESTRO_PATH)
        print(f"Dataset length: {len(dataset)}")
        for idx, (wav, src, tgt, __idx) in enumerate(dataset):
            src_dec, tgt_dec = tokenizer.decode(src), tokenizer.decode(tgt)

            if idx % 7 == 0 and idx < 100:
                print(idx)
                src_mid_dict = tokenizer._detokenize_midi_dict(
                    src_dec,
                    len_ms=30000,
                )

                src_mid = src_mid_dict.to_midi()
                src_mid.save(f"tests/test_results/dataset_{idx}.mid")
                torchaudio.save(
                    f"tests/test_results/wav_{idx}.wav", wav.unsqueeze(0), 16000
                )
                torchaudio.save(
                    f"tests/test_results/wav_aug_{idx}.wav",
                    audio_transform.aug_wav(wav.unsqueeze(0)),
                    16000,
                )
                plot_spec(
                    audio_transform(wav.unsqueeze(0)).squeeze(0), f"mel_{idx}"
                )

            self.assertTrue(tokenizer.unk_tok not in src_dec)
            self.assertTrue(tokenizer.unk_tok not in tgt_dec)
            for src_tok, tgt_tok in zip(src_dec[1:], tgt_dec):
                self.assertEqual(src_tok, tgt_tok)


class TestAug(unittest.TestCase):
    def test_spec(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        griffin_lim = torchaudio.transforms.GriffinLim(
            n_fft=2048,
            hop_length=160,
            power=1,
            n_iter=64,
        )

        spec = audio_transform.spec_transform(wav)
        shift_spec = audio_transform.shift_spec(spec, 1)
        shift_wav = griffin_lim(shift_spec)
        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        torchaudio.save("tests/test_results/shift.wav", shift_wav, SAMPLE_RATE)

        log_mel = log_mel_spectrogram(wav)
        plot_spec(log_mel.squeeze(0), "orig")

        _mel = audio_transform.mel_transform(spec)
        _log_mel = audio_transform.norm_mel(_mel)
        plot_spec(_log_mel.squeeze(0), "new")

    def test_pitch_aug(self):
        tokenizer = AmtTokenizer(return_tensors=True)
        tensor_pitch_aug_fn = tokenizer.export_tensor_pitch_aug()
        mid_dict = MidiDict.from_midi("tests/test_data/maestro2.mid")
        seq = tokenizer._tokenize_midi_dict(mid_dict, 0, 30000)
        src = tokenizer.encode(tokenizer.trunc_seq(seq, 4096))
        tgt = tokenizer.encode(tokenizer.trunc_seq(seq[1:], 4096))

        src = torch.stack((src, src, src))
        tgt = torch.stack((tgt, tgt, tgt))
        src_aug = tensor_pitch_aug_fn(src.clone(), shift=1)
        tgt_aug = tensor_pitch_aug_fn(tgt.clone(), shift=1)

        src_aug_dec = tokenizer.decode(src_aug[1])
        tgt_aug_dec = tokenizer.decode(tgt_aug[2])
        print(seq[:20])
        print(src_aug_dec[:20])
        print(tgt_aug_dec[:20])

        for tok, aug_tok in zip(seq, src_aug_dec):
            if type(tok) is tuple and aug_tok[0] in {"on", "off"}:
                self.assertEqual(tok[1] + 1, aug_tok[1])

        for src_tok, tgt_tok in zip(src_aug_dec[1:], tgt_aug_dec):
            self.assertEqual(src_tok, tgt_tok)

    def test_detune(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        griffin_lim = torchaudio.transforms.GriffinLim(
            n_fft=2048,
            hop_length=160,
            power=1,
            n_iter=64,
        )

        spec = audio_transform.spec_transform(wav)
        shift_spec = audio_transform.detune_spec(spec)
        shift_wav = griffin_lim(shift_spec)
        gl_wav = griffin_lim(spec)
        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        torchaudio.save("tests/test_results/orig_gl.wav", gl_wav, SAMPLE_RATE)
        torchaudio.save("tests/test_results/detune.wav", shift_wav, SAMPLE_RATE)

        log_mel = log_mel_spectrogram(wav)
        plot_spec(log_mel.squeeze(0), "orig")

        _mel = audio_transform.mel_transform(spec)
        _log_mel = audio_transform.norm_mel(_mel)
        plot_spec(_log_mel.squeeze(0), "new")

    def test_mels(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]
        wav_aug = audio_transform.aug_wav(
            audio_transform.distortion_aug_cpu(wav)
        )
        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        torchaudio.save("tests/test_results/aug.wav", wav_aug, SAMPLE_RATE)

        wavs = torch.stack((wav[0], wav[0], wav[0]))
        mels = audio_transform(wavs)
        for idx in range(mels.shape[0]):
            plot_spec(mels[idx], idx)

    def test_distortion(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        res = audio_transform.apply_distortion(wav)
        torchaudio.save("tests/test_results/dist.wav", res, SAMPLE_RATE)

    def test_bandpass(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/147.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        res = audio_transform.apply_bandpass(wav)
        torchaudio.save("tests/test_results/bandpass.wav", res, SAMPLE_RATE)

    def test_applause(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        res = audio_transform.apply_applause(wav)
        torchaudio.save("tests/test_results/applause.wav", res, SAMPLE_RATE)

    def test_reduction(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        res = audio_transform.apply_reduction(wav)
        torchaudio.save("tests/test_results/reduction.wav", res, SAMPLE_RATE)

    def test_noise(self):
        SAMPLE_RATE, CHUNK_LEN = 16000, 30
        audio_transform = AudioTransform()
        wav, sr = torchaudio.load("tests/test_data/maestro.wav")
        wav = torchaudio.functional.resample(wav, sr, SAMPLE_RATE).mean(
            0, keepdim=True
        )[:, : SAMPLE_RATE * CHUNK_LEN]

        torchaudio.save("tests/test_results/orig.wav", wav, SAMPLE_RATE)
        res = audio_transform.apply_noise(wav)
        torchaudio.save("tests/test_results/noise.wav", res, SAMPLE_RATE)


class TestDataLoader(unittest.TestCase):
    def load_data(self, dataloader, num_batches=100):
        for idx, data in enumerate(dataloader):
            if idx >= num_batches:
                break

    def test_profile_dl(self):
        train_dataloader, val_dataloader = get_dataloaders(
            train_data_path="/weka/proj-aria/aria-amt/data/train.jsonl",
            val_data_path="/weka/proj-aria/aria-amt/data/train.jsonl",
            batch_size=16,
            num_workers=0,
        )

        profiler = cProfile.Profile()
        profiler.enable()
        self.load_data(train_dataloader, num_batches=10)
        profiler.disable()
        stats = pstats.Stats(profiler).sort_stats("cumulative")
        stats.print_stats()


if __name__ == "__main__":
    unittest.main()
