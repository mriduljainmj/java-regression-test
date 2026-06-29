#!/bin/bash
# Setup auto-update hooks for PROJECT.md
# 
# Usage:
#   ./setup-hooks.sh

set -e

echo "🔧 Setting up PROJECT.md auto-update hooks..."

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/.githooks"

# Create .githooks directory if it doesn't exist
if [ ! -d "$HOOKS_DIR" ]; then
    echo "📁 Creating .githooks directory..."
    mkdir -p "$HOOKS_DIR"
fi

# Make hooks executable
echo "📝 Making hooks executable..."
chmod +x "$HOOKS_DIR/pre-commit" 2>/dev/null || true

# Configure git to use .githooks
echo "⚙️  Configuring git hooks path..."
git config core.hooksPath "$HOOKS_DIR"

echo ""
echo "✅ Hooks configured successfully!"
echo ""
echo "📋 What now happens automatically:"
echo "   1. When you stage code changes (.java, .cs, .feature files)"
echo "   2. The pre-commit hook runs update-project-mindmap.py"
echo "   3. PROJECT.md is updated with new API endpoints, services, tests"
echo "   4. PROJECT.md is automatically staged with your commit"
echo ""
echo "🚀 Next steps:"
echo "   - Make changes to any controller, service, or feature file"
echo "   - Run: git add <files>"
echo "   - PROJECT.md will be updated automatically"
echo "   - Run: git commit -m 'your message'"
echo ""
echo "📚 Manual update (anytime):"
echo "   python3 update-project-mindmap.py"
echo ""
