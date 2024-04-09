#!/bin/sh
#SBATCH --output=vanilla__%x.%j.out
#SBATCH --error=vanilla__%x.%j.err
#SBATCH -N 1
#SBATCH -n 1
#SBATCH --time=24:00:00
#SBATCH --gres=gpu:1
#SBATCH --mem-per-gpu=100GB
#SBATCH --cpus-per-gpu=20
#SBATCH --partition=isi

source /home1/${USER}/.bashrc
conda activate py311

PROJ_DIR=/project/jonmay_231/spangher/Projects/aria-amt
OUTPUT_DIR="$PROJ_DIR/experiments/vanilla_files"

if [ ! -d "$OUTPUT_DIR" ]; then
  python process_maestro.py \
    -split test \
    -maestro_dir "$PROJ_DIR/../maestro-v3.0.0/maestro-v3.0.0.csv" \
    -output_dir $OUTPUT_DIR \
    -midi_col_name 'midi_filename' \
    -audio_col_name 'audio_filename'
fi

# run google inference
echo "Running google inference"
GOOGLE_OUTPUT_DIR="$OUTPUT_DIR/google_t5_transcriptions"
python baselines/google_t5/transcribe_new_files.py \
    -input_dir_to_transcribe $OUTPUT_DIR \
    -output_dir $GOOGLE_OUTPUT_DIR

echo "Running giant midi inference"
GIANT_MIDI_OUTPUT_DIR="$OUTPUT_DIR/giant_midi_transcriptions"
python baselines/giantmidi/transcribe_new_files.py \
    -input_dir_to_transcribe $OUTPUT_DIR \
    -output_dir $GIANT_MIDI_OUTPUT_DIR

echo "Running hft inference"
HFT_OUTPUT_DIR="$OUTPUT_DIR/hft_transcriptions"
python baselines/hft_transformer/transcribe_new_files.py \
    -input_dir_to_transcribe $OUTPUT_DIR \
    -output_dir $HFT_OUTPUT_DIR