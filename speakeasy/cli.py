"""`speakeasy` console-script entry point.

    speakeasy app                run the menu-bar app (what `brew services` runs)
    speakeasy listener           run the listener without the menu bar
    speakeasy speak <file> ...   dev tool: run one rewrite+say pass, no server
    speakeasy init               wire up Claude Code + Codex, seed config.json
    speakeasy doctor             check config, hooks and listener; start it if down
    speakeasy uninstall          reverse `init`
    speakeasy claude-hook        (used BY Claude Code's Stop hook, not by you)
    speakeasy claude-ask-hook    (used BY Claude Code's AskUserQuestion hook)
    speakeasy codex-notify       (used BY Codex's `notify` hook)
"""
import sys

USAGE = ("usage: speakeasy {app|listener|speak|init|doctor|uninstall|"
         "claude-hook|claude-ask-hook|codex-notify} ...")


def main():
    if len(sys.argv) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(1)

    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "app":
        from speakeasy import app
        app.main()
    elif cmd == "listener":
        from speakeasy import listener
        listener.main()
    elif cmd == "speak":
        from speakeasy import speak
        sys.argv = ["speakeasy speak"] + rest
        speak.main()
    elif cmd == "init":
        from speakeasy import install
        install.cmd_init(rest)
    elif cmd == "doctor":
        from speakeasy import install
        sys.exit(install.cmd_doctor(rest))
    elif cmd == "uninstall":
        from speakeasy import install
        install.cmd_uninstall(rest)
    elif cmd == "claude-hook":
        from speakeasy import hooks
        hooks.claude_hook()
    elif cmd == "claude-ask-hook":
        from speakeasy import hooks
        hooks.claude_ask_hook()
    elif cmd == "codex-notify":
        from speakeasy import hooks
        hooks.codex_notify(rest)
    else:
        print(f"unknown subcommand: {cmd}\n{USAGE}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
