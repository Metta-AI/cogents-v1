"""Tests for the fibonacci demo app image."""

from pathlib import Path

from cogos.image.spec import load_image


def test_cogent_v1_fibonacci_loads():
    spec = load_image(Path("images/cogos"))
    assert "mnt/boot/fibonacci/fibonacci.md" in spec.files


def test_cogent_v1_fibonacci_files_and_prompt():
    spec = load_image(Path("images/cogos"))
    fibonacci_files = {k for k in spec.files if k.startswith("mnt/boot/fibonacci/")}

    assert "mnt/boot/fibonacci/fibonacci.md" in fibonacci_files
    prompt = spec.files["mnt/boot/fibonacci/fibonacci.md"]
    assert "fibonacci:poke" in prompt
    assert "If this is the first time, reply with `0`." in prompt
    assert "look back at the prior conversation in this session" in prompt
    assert "Reply with only the next Fibonacci number." in prompt


def test_cogent_v1_fibonacci_no_init():
    spec = load_image(Path("images/cogos"))
    channel_names = {c["name"] for c in spec.channels}
    assert "fibonacci:poke" not in channel_names
