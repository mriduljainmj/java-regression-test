# Auto-Update PROJECT.md System

Automatically keeps `PROJECT.md` (the AI knowledge base) in sync with code changes.

## Why This Exists

When code changes, `PROJECT.md` needs to be updated with:
- New/modified API endpoints
- Updated business logic (service methods)
- New test scenarios (Gherkin features)

**Without this system**: AI re-explores the codebase, slower generation, stale knowledge.  
**With this system**: PROJECT.md auto-updates → AI has current knowledge → faster, accurate tests.

---

## 🚀 Quick Start (30 seconds)

### 1. Setup (One-Time)

**Windows:**
```bash
setup-hooks.bat
```

**Mac/Linux:**
```bash
./setup-hooks.sh
```

### 2. Make a Code Change

```bash
# Edit any controller, service, or feature file
git add <changed-files>
git commit -m "your message"
# ✅ Pre-commit hook runs automatically
# ✅ PROJECT.md updated and staged
```

### 3. Push

```bash
git push origin develop
# ✅ GitHub Actions auto-updates PROJECT.md
# ✅ AI reads current knowledge base on next run
```

---

## How It Works

### Flow Diagram

```
Developer changes code (*.java, *.cs, *.feature)
        │
        ├─ Local: pre-commit hook triggers
        │  └─ update-project-mindmap.py scans changes
        │     ├─ Extract: @GetMapping, @PostMapping, etc. → endpoints
        │     ├─ Extract: public methods → service logic
        │     ├─ Extract: Scenario: → test coverage
        │     └─ Update PROJECT.md + auto-stage
        │
        ├─ Developer: git commit (PROJECT.md included)
        │
        └─ Push to GitHub
                 │
                 └─ GitHub Actions: auto-update-mindmap.yml
                    └─ Double-checks PROJECT.md currency
                       └─ Auto-commits if needed
                              │
                              ▼
                       PROJECT.md is guaranteed current
                              │
                              ├─ testgen-agent reads it
                              └─ Has all current APIs, methods, patterns
                                 └─ Generates accurate tests immediately
```

### What Gets Auto-Updated

| File Change | Detects | Updates PROJECT.md |
|---|---|---|
| `*Controller.java` | Endpoints (`@Get/@Post/@Put/@Delete/@Patch`) | PART 2: Java Endpoints |
| `*Controller.cs` | Endpoints (`[HttpGet]/[HttpPost]/[HttpPut]/[HttpDelete]`) | PART 2: .NET Endpoints |
| `*Service.java` | Public method signatures | PART 3: Service Logic |
| `*Service.cs` | Public method signatures | PART 3: Service Logic |
| `*.feature` | Scenario names and counts | PART 5: Test Coverage |

Each update is marked with `[AUTO-UPDATE]` prefix so you can distinguish auto-generated vs. manual content.

---

## Components

### 1. `update-project-mindmap.py` (Main Script)

- Scans changed files
- Extracts APIs, methods, scenarios
- Updates PROJECT.md with `[AUTO-UPDATE]` markers
- Optionally auto-commits changes

**Manual usage:**
```bash
# Update based on git changes
python3 update-project-mindmap.py

# Auto-commit changes
python3 update-project-mindmap.py --auto-commit

# Specify files manually
export CHANGED_FILES="file1.java,file2.cs"
python3 update-project-mindmap.py
```

### 2. `.github/workflows/auto-update-mindmap.yml` (CI/CD)

- Runs automatically on push to develop/main
- Triggers only when code files change (*.java, *.cs, *.feature)
- Auto-commits PROJECT.md updates
- Pushes back to repo

### 3. `.githooks/pre-commit` (Local Hook)

- Runs before each local commit
- Updates PROJECT.md locally
- Auto-stages changes for the commit
- Saves developer time

**To disable temporarily:**
```bash
git commit --no-verify -m "skip hook"
```

### 4. `setup-hooks.sh` / `setup-hooks.bat` (Setup Scripts)

- Configures git to use `.githooks/` directory
- One-command setup for all platforms
- No additional configuration needed

---

## Example Workflows

### Scenario 1: Add Java Endpoint

```java
// ProductController.java
@PostMapping("/{id}/apply-loyalty")
public void applyLoyalty(@PathVariable Long id) { }
```

**What happens:**
```bash
git add java-component/src/main/java/com/example/products/ProductController.java
git commit -m "feat: add loyalty endpoint"
# ✅ Hook runs: detects new endpoint
# ✅ PROJECT.md updated:
#    [AUTO-UPDATE] Java endpoints detected:
#    - POST /api/v1/products/{id}/apply-loyalty (applyLoyalty)
# ✅ PROJECT.md auto-staged

git push origin develop
# ✅ CI verifies and auto-commits PROJECT.md
```

### Scenario 2: Update Service Logic

```csharp
// ProductService.cs
public (double totalPrice, int discountPercent) ApplySeasonalDiscount(int qty) { }
```

**What happens:**
```bash
git add dotnet-component/Services/ProductService.cs
git commit -m "refactor: add seasonal discount"
# ✅ Hook updates PROJECT.md:
#    [AUTO-UPDATE] Service methods detected:
#    ProductService:
#    - ApplySeasonalDiscount() → (double, int)

git push
# ✅ CI verifies PROJECT.md
```

### Scenario 3: Add Test Scenarios

```gherkin
# dotnet-component/Tests/Features/loyalty_discount.feature
Feature: Loyalty Discount
  Scenario: Apply loyalty tier 1
    Given a customer with tier 1 loyalty
    When ordering 10+ items
    Then apply 5% discount
```

**What happens:**
```bash
git add dotnet-component/Tests/Features/loyalty_discount.feature
git commit -m "test: add loyalty scenarios"
# ✅ Hook updates PROJECT.md:
#    [AUTO-UPDATE] Feature scenarios detected:
#    Loyalty Discount (5 scenarios):
#    - Apply loyalty tier 1
#    - Apply loyalty tier 2
#    (etc...)

git push
# ✅ AI knows about new test patterns immediately
```

---

## Setup & Configuration

### Initial Setup

**Step 1: Run setup script**

Windows:
```bash
setup-hooks.bat
```

Mac/Linux:
```bash
./setup-hooks.sh
```

**Step 2: Verify**

```bash
# Should show: .githooks
git config core.hooksPath

# Test manually
python3 update-project-mindmap.py
```

### Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `CHANGED_FILES` | Manual file list for update | `"file1.java,file2.cs"` |
| `AUTO_COMMIT` | Auto-commit changes | (set to enable) |

### Disable Hook Temporarily

```bash
# Skip hook for a single commit
git commit --no-verify -m "skip hook"

# Disable globally (not recommended)
git config core.hooksPath ""
# Re-enable
./setup-hooks.sh  # or setup-hooks.bat
```

---

## Troubleshooting

### Hook Not Running

**Check if configured:**
```bash
git config core.hooksPath
# Should output: .githooks
```

**Re-setup if needed:**
```bash
./setup-hooks.sh    # Mac/Linux
setup-hooks.bat     # Windows
```

**Make hook executable (Mac/Linux):**
```bash
chmod +x .git/hooks/pre-commit
```

### PROJECT.md Not Updating

**Test manually:**
```bash
python3 update-project-mindmap.py
```

**Check for Python:**
```bash
python3 --version
# Should be 3.7+
```

**Check changed files:**
```bash
git diff --name-only HEAD~1 HEAD
```

### CI Workflow Not Triggering

**Check GitHub Actions:**
1. Settings → Actions → Permissions
2. Select "Allow all actions" (or at least allow our workflow)
3. Check workflow file exists: `.github/workflows/auto-update-mindmap.yml`

**Check workflow isn't disabled:**
```bash
# View workflow status in GitHub Actions tab
```

---

## How This Helps testgen-agent

```
Without auto-update:
  ❌ CODE CHANGES → AI doesn't know → OLD knowledge base → Wrong tests

With auto-update:
  ✅ CODE CHANGES → PROJECT.md auto-updates → AI reads current knowledge → Accurate tests
```

### Example: New Endpoint Added

1. Dev adds: `POST /api/v1/products/{id}/validate-stock`
2. Hook runs: Detects new endpoint
3. PROJECT.md updated with new endpoint
4. Next testgen-agent run: Reads current PROJECT.md
5. Generates accurate test scenarios for stock validation

---

## Architecture Details

### What the Script Scans

**Java Controllers:**
- Extracts `@RestController` base path
- Finds `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`
- Records: HTTP method, path, handler name

**C# Controllers:**
- Extracts `[Route(...)]` base path
- Finds `[HttpGet]`, `[HttpPost]`, `[HttpPut]`, `[HttpDelete]`, `[HttpPatch]`
- Records: HTTP method, path, handler name

**Services (Java & C#):**
- Extracts all `public` methods
- Records: method name, return type

**Features (Gherkin):**
- Extracts feature name
- Finds all `Scenario:` entries
- Records: scenario names, count

### How It Updates PROJECT.md

1. Finds relevant PART heading in PROJECT.md
2. Inserts `[AUTO-UPDATE]` section with new endpoints/methods/scenarios
3. Preserves existing manual content
4. Adds timestamp
5. Saves file

---

## Files Overview

| File | Purpose | Audience |
|---|---|---|
| `PROJECT.md` | AI knowledge base (auto-updated) | AI agents, developers |
| `update-project-mindmap.py` | Update script | Developers, CI/CD |
| `.github/workflows/auto-update-mindmap.yml` | CI/CD workflow | DevOps, maintainers |
| `.githooks/pre-commit` | Local hook | Developers |
| `setup-hooks.sh` / `setup-hooks.bat` | Setup script | All platforms |

---

## Key Features

✅ **Automatic** - Runs on every commit (local) and push (CI)  
✅ **Non-Destructive** - Only adds updates, preserves manual content  
✅ **Timestamped** - Tracks when updates happened  
✅ **Marked** - Uses `[AUTO-UPDATE]` prefix for clarity  
✅ **Two-Layer** - Local hook + CI verification  
✅ **Zero Config** - Just run setup script  
✅ **Fast** - Minimal overhead on commits  

---

## Future Enhancements

- [ ] Extract request/response schemas from annotations
- [ ] Track deprecated endpoints
- [ ] Monitor database migrations
- [ ] Generate OpenAPI specs from PROJECT.md
- [ ] Configuration change tracking
- [ ] Dependency update monitoring
- [ ] Email notifications on major changes

---

## Support & Debugging

**Enable verbose logging:**
```bash
python3 -u update-project-mindmap.py
```

**Check git history of PROJECT.md:**
```bash
git log --oneline PROJECT.md
git diff HEAD~1 PROJECT.md | grep "AUTO-UPDATE"
```

**Manual force-update:**
```bash
git add <files>
python3 update-project-mindmap.py --auto-commit
```

---

## Summary

This system ensures your **PROJECT.md knowledge base stays current automatically**:

- ✅ Developer changes code
- ✅ Hook detects changes
- ✅ PROJECT.md updated automatically
- ✅ AI always has current knowledge
- ✅ Tests generated accurately

**Ready to use:** Just run `./setup-hooks.sh` (or `.bat` on Windows) once, then commit normally! 🚀
