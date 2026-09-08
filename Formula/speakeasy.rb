class Speakeasy < Formula
  include Language::Python::Virtualenv

  desc "Speak Claude Code / Codex turns aloud via local Kokoro TTS"
  homepage "https://github.com/jimfleming/speakeasy"
  url "https://github.com/jimfleming/speakeasy.git",
      tag:      "v0.2.2",
      revision: "6f0796ebca439cdb8ab6cfdd9bcc7e29d99d7f14"
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

  service do
    run [opt_bin/"speakeasy", "app"]
    keep_alive successful_exit: false
    log_path var/"log/speakeasy.log"
    error_log_path var/"log/speakeasy.err.log"
  end

  def caveats
    <<~EOS
      Wire speakeasy into Claude Code and/or Codex, and seed your API key:
        speakeasy init

      Then start the menu-bar app (auto-restarts on crash, runs at login):
        brew services start speakeasy
    EOS
  end

  test do
    assert_match "usage: speakeasy", shell_output("#{bin}/speakeasy 2>&1", 1)
  end
end
