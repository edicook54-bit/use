import subprocess
import sys

# ─────────────────────────────────────────────
#  AUTO INSTALL PACKAGES
# ─────────────────────────────────────────────

def install_packages():
    packages = ["google-genai", "pydub"]
    print("=" * 60)
    print("  📦 Checking and Installing Required Packages...")
    print("=" * 60)
    for package in packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"  ✅ {package} already installed")
        except ImportError:
            print(f"  ⬇️  Installing {package}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"  ✅ {package} installed successfully")

install_packages()

# ─────────────────────────────────────────────
#  NOW IMPORT EVERYTHING
# ─────────────────────────────────────────────

import os
import re
import time
import struct
import mimetypes
from google import genai
from google.genai import types
from pydub import AudioSegment


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def save_binary_file(file_name: str, data: bytes):
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"  ✅ Saved: {file_name}")


def parse_audio_mime_type(mime_type: str) -> dict:
    bits_per_sample = 16
    rate = 24000
    parts = mime_type.split(";")
    for param in parts:
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate = int(param.split("=", 1)[1])
            except (ValueError, IndexError):
                pass
        elif param.startswith("audio/L"):
            try:
                bits_per_sample = int(param.split("L", 1)[1])
            except (ValueError, IndexError):
                pass
    return {"bits_per_sample": bits_per_sample, "rate": rate}


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    parameters      = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate     = parameters["rate"]
    num_channels    = 1
    data_size       = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align     = num_channels * bytes_per_sample
    byte_rate       = sample_rate * block_align
    chunk_size      = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", chunk_size, b"WAVE",
        b"fmt ", 16, 1, num_channels,
        sample_rate, byte_rate, block_align,
        bits_per_sample, b"data", data_size,
    )
    return header + audio_data


# ─────────────────────────────────────────────
#  TEXT SPLITTER
# ─────────────────────────────────────────────

def split_text(text: str, max_chars: int = 800) -> list:
    """
    Split text into chunks at sentence boundaries.
    Supports Bangla (।) English (. ! ?) sentence endings.
    """
    sentences = re.split(r'(?<=[।.!?])\s+', text.strip())
    chunks  = []
    current = ""

    for sentence in sentences:
        # If single sentence is too long, hard split it
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i:i + max_chars].strip())
            continue

        if len(current) + len(sentence) + 1 <= max_chars:
            current += " " + sentence if current else sentence
        else:
            if current:
                chunks.append(current.strip())
            current = sentence

    if current:
        chunks.append(current.strip())

    return chunks


# ─────────────────────────────────────────────
#  GEMINI TTS — SINGLE CHUNK
# ─────────────────────────────────────────────

def generate_audio_for_chunk(
    client,
    text_chunk: str,
    voice_name: str,
    model: str,
    audio_profile: str,
    directors_note: str,
    context: str,
    chunk_index: int,
    output_dir: str,
) -> str:
    """
    Send one chunk to Gemini TTS.
    Returns the saved file path or None on failure.
    """

    prompt = f"""Read the following transcript based on the audio profile and director's note.

# Audio Profile
{audio_profile}

# Director's note
{directors_note}

## Sample Context:
{context}

## Transcript:
{text_chunk}"""

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    ]

    config = types.GenerateContentConfig(
        temperature=1,
        response_modalities=["audio"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name
                )
            )
        ),
    )

    saved_files = []

    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            if chunk.parts is None:
                continue

            part = chunk.parts[0]
            if part.inline_data and part.inline_data.data:
                inline_data    = part.inline_data
                data_buffer    = inline_data.data
                file_extension = mimetypes.guess_extension(inline_data.mime_type)

                if file_extension is None:
                    file_extension = ".wav"
                    data_buffer = convert_to_wav(
                        inline_data.data, inline_data.mime_type
                    )

                file_path = os.path.join(
                    output_dir,
                    f"chunk_{chunk_index:03d}{file_extension}"
                )
                save_binary_file(file_path, data_buffer)
                saved_files.append(file_path)

            else:
                if text := getattr(chunk, "text", None):
                    print(f"  ℹ️  Model response: {text}")

    except Exception as e:
        print(f"  ❌ Error on chunk {chunk_index}: {e}")
        return None

    return saved_files[0] if saved_files else None


# ─────────────────────────────────────────────
#  COMBINE WAV FILES
# ─────────────────────────────────────────────

def combine_wav_files(file_paths: list, output_path: str):
    """Stitch multiple WAV files into one using pydub."""
    print("\n🔗 Combining all audio chunks into one file...")
    combined = AudioSegment.empty()
    for fp in file_paths:
        try:
            seg = AudioSegment.from_wav(fp)
            combined += seg
            print(f"  ➕ Added: {fp}")
        except Exception as e:
            print(f"  ⚠️  Could not load {fp}: {e}")

    combined.export(output_path, format="wav")
    print(f"  ✅ Final audio saved: {output_path}")


# ─────────────────────────────────────────────
#  USER INPUT HELPERS
# ─────────────────────────────────────────────

def ask_multiline(prompt_text: str) -> str:
    """
    Let the user paste multiple lines of text.
    Type END on a new line to finish.
    """
    print(prompt_text)
    print("  ┌─────────────────────────────────────────┐")
    print("  │  Paste your text below.                 │")
    print("  │  When done type  END  and press Enter   │")
    print("  └─────────────────────────────────────────┘")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return "\n".join(lines)


AVAILABLE_VOICES = [
    "Zephyr",   # Bright
    "Charon",   # Informational
    "Puck",     # Upbeat
    "Kore",     # Firm
    "Fenrir",   # Excitable
    "Aoede",    # Breezy
    "Leda",     # Youthful
    "Orus",     # Firm
    "Schedar",  # Even
]

def ask_voice() -> str:
    print("\n🎙  Available Voices:")
    print("  ┌────┬────────────┬──────────────────┐")
    print("  │ No │ Voice      │ Style            │")
    print("  ├────┼────────────┼──────────────────┤")
    styles = [
        "Bright",
        "Informational",
        "Upbeat",
        "Firm",
        "Excitable",
        "Breezy",
        "Youthful",
        "Firm",
        "Even / Balanced",
    ]
    for i, (v, s) in enumerate(zip(AVAILABLE_VOICES, styles), 1):
        print(f"  │ {i:<2} │ {v:<10} │ {s:<16} │")
    print("  └────┴────────────┴──────────────────┘")

    while True:
        choice = input("\n  Pick a number or type the voice name: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(AVAILABLE_VOICES):
                return AVAILABLE_VOICES[idx]
        elif choice in AVAILABLE_VOICES:
            return choice
        print("  ⚠️  Invalid choice, please try again.")


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    print("\n" + "=" * 60)
    print("   🎧  Gemini TTS — Automated Long Text Audio Generator")
    print("=" * 60)

    # ── 1. API KEY ──────────────────────────────────────────────
    print("\n🔑 STEP 1 — API KEY")
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        print(f"  ✅ Found API key in environment variable.")
    else:
        api_key = input("  Enter your Gemini API Key: ").strip()
    if not api_key:
        print("  ❌ No API key provided. Exiting.")
        return

    # ── 2. MODEL ────────────────────────────────────────────────
    print("\n🤖 STEP 2 — MODEL")
    default_model = "gemini-3.1-flash-tts-preview"
    model_input   = input(
        f"  Model name (press Enter for default [{default_model}]): "
    ).strip()
    model = model_input if model_input else default_model
    print(f"  ✅ Using model: {model}")

    # ── 3. VOICE ────────────────────────────────────────────────
    print("\n🎙  STEP 3 — VOICE")
    voice_name = ask_voice()
    print(f"  ✅ Using voice: {voice_name}")

    # ── 4. AUDIO PROFILE ────────────────────────────────────────
    print("\n🎭 STEP 4 — AUDIO PROFILE")
    print("  Example: A deep, resonant narrator of mysteries.")
    print("  Example: A warm, friendly storyteller.")
    audio_profile = input("  Your audio profile: ").strip()
    if not audio_profile:
        audio_profile = "A clear and natural narrator."
    print(f"  ✅ Profile set.")

    # ── 5. DIRECTOR'S NOTE ──────────────────────────────────────
    print("\n🎬 STEP 5 — DIRECTOR'S NOTE")
    print("  Example: Style: Calm. Pace: Moderate. Accent: British (GB).")
    print("  Example: Style: Whisper. Pace: Slow. Accent: American.")
    directors_note = input("  Your director's note: ").strip()
    if not directors_note:
        directors_note = "Style: Natural. Pace: Moderate."
    print(f"  ✅ Note set.")

    # ── 6. CONTEXT ──────────────────────────────────────────────
    print("\n📖 STEP 6 — CONTEXT")
    print("  Example: Reading a philosophy book in Bangla.")
    print("  Example: Narrating a mystery novel.")
    context = input("  Your context: ").strip()
    if not context:
        context = "General narration."
    print(f"  ✅ Context set.")

    # ── 7. TEXT INPUT ───────────────────────────────────────────
    print("\n📝 STEP 7 — YOUR TEXT")
    big_text = ask_multiline("")
    if not big_text.strip():
        print("  ❌ No text provided. Exiting.")
        return
    word_count = len(big_text.split())
    char_count = len(big_text)
    print(f"  ✅ Text received — {word_count} words, {char_count} characters.")

    # ── 8. OUTPUT FILE NAME ─────────────────────────────────────
    print("\n💾 STEP 8 — OUTPUT FILE NAME")
    output_name = input(
        "  Output file name without extension (e.g. my_audiobook): "
    ).strip()
    if not output_name:
        output_name = "output_audio"
    print(f"  ✅ Will save as: {output_name}.wav")

    # ── 9. DELAY ────────────────────────────────────────────────
    print("\n⏱  STEP 9 — DELAY BETWEEN API CALLS")
    print("  Recommended: 12 seconds (safe for free tier)")
    print("  Minimum    : 5  seconds (may hit rate limit)")
    delay_input = input("  Delay in seconds (press Enter for 12): ").strip()
    try:
        delay_seconds = int(delay_input)
    except ValueError:
        delay_seconds = 12
    print(f"  ✅ Delay set to {delay_seconds} seconds.")

    # ── 10. CHUNK SIZE ──────────────────────────────────────────
    print("\n✂️  STEP 10 — CHUNK SIZE")
    print("  Each chunk is sent as one API request.")
    print("  Recommended: 800 characters per chunk.")
    chunk_input = input("  Characters per chunk (press Enter for 800): ").strip()
    try:
        max_chars = int(chunk_input)
    except ValueError:
        max_chars = 800
    print(f"  ✅ Chunk size: {max_chars} characters.")

    # ── 11. CONFIRM ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  📋 SUMMARY — Review before starting")
    print("=" * 60)
    print(f"  Model        : {model}")
    print(f"  Voice        : {voice_name}")
    print(f"  Audio Profile: {audio_profile[:50]}")
    print(f"  Director Note: {directors_note[:50]}")
    print(f"  Context      : {context[:50]}")
    print(f"  Text Length  : {char_count} characters / {word_count} words")
    print(f"  Output File  : {output_name}.wav")
    print(f"  Delay        : {delay_seconds} seconds between chunks")
    print(f"  Chunk Size   : {max_chars} characters")

    chunks = split_text(big_text, max_chars=max_chars)
    total  = len(chunks)
    est    = total * delay_seconds

    print(f"  Total Chunks : {total}")
    print(f"  Est. Time    : ~{est} seconds (~{est // 60} min {est % 60} sec)")
    print("=" * 60)

    confirm = input("\n  ▶️  Start generating? (yes/no): ").strip().lower()
    if confirm not in ["yes", "y"]:
        print("  ❌ Cancelled.")
        return

    # ── 12. SETUP ────────────────────────────────────────────────
    output_dir = "tts_chunks"
    os.makedirs(output_dir, exist_ok=True)
    client = genai.Client(api_key=api_key)

    # ── 13. GENERATE ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  🚀 Starting Audio Generation...")
    print("=" * 60)

    saved_files = []

    for i, chunk_text in enumerate(chunks, 1):
        print(f"\n🔊 Chunk {i}/{total}")
        print(f"   Characters : {len(chunk_text)}")
        print(f"   Preview    : {chunk_text[:80]}...")

        file_path = generate_audio_for_chunk(
            client        = client,
            text_chunk    = chunk_text,
            voice_name    = voice_name,
            model         = model,
            audio_profile = audio_profile,
            directors_note= directors_note,
            context       = context,
            chunk_index   = i,
            output_dir    = output_dir,
        )

        if file_path:
            saved_files.append(file_path)
            print(f"  ✅ Chunk {i} done!")
        else:
            print(f"  ⚠️  Chunk {i} failed, continuing...")

        if i < total:
            print(f"  ⏳ Waiting {delay_seconds}s...")
            for remaining in range(delay_seconds, 0, -1):
                print(f"     {remaining}s remaining...", end="\r")
                time.sleep(1)
            print(" " * 30, end="\r")

    # ── 14. COMBINE ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  🔗 COMBINING AUDIO FILES")
    print("=" * 60)

    if len(saved_files) == 0:
        print("  ❌ No audio files were generated. Check errors above.")
        return

    final_path = f"{output_name}.wav"

    if len(saved_files) == 1:
        os.rename(saved_files[0], final_path)
        print(f"  ✅ Single chunk saved as: {final_path}")
    else:
        combine_wav_files(saved_files, final_path)

    # ── 15. DONE ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  🎉 ALL DONE!")
    print("=" * 60)
    print(f"  📁 Individual chunks : ./{output_dir}/")
    print(f"  🎵 Final audio file  : ./{final_path}")
    print(f"  ✅ Generated {len(saved_files)} of {total} chunks successfully.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
