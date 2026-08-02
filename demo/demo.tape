# VHS tape for the README demo GIF — https://github.com/charmbracelet/vhs
#
# Prep (once):
#   brew install vhs
#   uv tool install <repo>          # agent-mcts on PATH
#   uv tool install pytest          # value fn for the toy repo
#   ./demo/setup-toy-repo.sh /tmp/agent-mcts-demo
# Record:
#   cd /tmp/agent-mcts-demo && vhs /path/to/repo/demo/demo.tape
# Then copy demo.gif into demo/ and reference it from the README.

Output demo.gif

Set FontSize 15
Set Width 1100
Set Height 650
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set WaitTimeout 300s

# invisible setup: tool paths + claude binary override if the shell needs them
Hide
Type `export PATH="$HOME/.local/bin:$PATH"`
Enter
Type `clear`
Enter
Show

Type `agent-mcts run "fix the broken add() in calc.py"`
Enter
Sleep 2s
Type "y"
Enter

# wait for the search to finish (the closing hint line mentions `apply`)
Wait+Screen /agent-mcts apply/
Sleep 2s

Type `agent-mcts apply`
Enter
Sleep 2s
Type `git diff --cached`
Enter
Sleep 6s
