# VHS tape for the README demo GIF — https://github.com/charmbracelet/vhs
#
# Prep (once):
#   brew install vhs
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

Type `agent-mcts run "fix the broken add() in calc.py" -n 4`
Enter
Sleep 3s
Type "y"
Enter

# One haiku episode takes ~10-30s; give the search room to finish.
Sleep 90s

Type "agent-mcts apply"
Enter
Sleep 3s
Type "git diff --cached"
Enter
Sleep 5s
