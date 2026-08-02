#!/bin/sh
# Create a tiny repo with a failing test, for recording the README demo.
# Usage: ./demo/setup-toy-repo.sh /tmp/agent-mcts-demo
set -eu

dir="${1:?usage: setup-toy-repo.sh <dir>}"
rm -rf "$dir"
mkdir -p "$dir"
cd "$dir"

git init -q
cat > calc.py << 'EOF'
def add(a, b):
    return a - b
EOF
cat > test_calc.py << 'EOF'
from calc import add


def test_add():
    assert add(1, 2) == 3


def test_add_negative():
    assert add(-1, -2) == -3
EOF
cat > pytest.ini << 'EOF'
[pytest]
EOF
git add -A
git -c user.name=demo -c user.email=demo@example.com commit -qm "init"

echo "Toy repo ready at $dir"
echo "Record with:  cd $dir && vhs <repo>/demo/demo.tape"
