class Speakeasy < Formula
  include Language::Python::Virtualenv

  desc "Speak Claude Code / Codex turns aloud via local Kokoro TTS"
  homepage "https://github.com/jimfleming/speakeasy"
  url "https://github.com/jimfleming/speakeasy.git",
      tag:      "v0.2.3",
      revision: "52ff65052fd9cac9791044eb4233e680c531d6b0"
  license "Apache-2.0"

  depends_on arch: :arm64
  depends_on "espeak-ng"
  depends_on macos: :ventura
  depends_on "python@3.12"

  def install
    virtualenv_create(libexec, "python3.12")
    system formula_opt_bin("python@3.12")/"python3.12", "-m", "pip",
           "--python=#{libexec}/bin/python", "install", "--no-cache-dir", buildpath
    bin.install_symlink libexec/"bin/speakeasy"
  end

  def caveats
    <<~EOS
      Wire speakeasy into Claude Code and/or Codex, seed your API key, and
      start the menu-bar app:
        speakeasy init

      It installs a LaunchAgent so the app runs at login. If the icon does not
      appear, `speakeasy doctor` reports why.
    EOS
  end

  test do
    assert_match "usage: speakeasy", shell_output("#{bin}/speakeasy 2>&1", 1)
  end
end
