#!/usr/bin/env python3
"""
Auto-update PROJECT.md when code changes are detected.
Scans controllers, services, and features for changes and updates the knowledge base.

Usage:
  python update-project-mindmap.py [--auto-commit]
  
Environment:
  CHANGED_FILES: Comma-separated list of changed files (from git)
  AUTO_COMMIT: If set, auto-commit PROJECT.md changes
"""

import os
import re
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

class ProjectMindmapUpdater:
    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root).resolve()
        self.project_md = self.repo_root / "PROJECT.md"
        self.changed_files = self._get_changed_files()
        self.updates = []
        
    def _get_changed_files(self) -> List[str]:
        """Get list of changed files from env or git diff"""
        changed = os.environ.get("CHANGED_FILES", "").split(",")
        changed = [f.strip() for f in changed if f.strip()]
        
        if not changed:
            try:
                result = subprocess.run(
                    ["git", "diff", "--name-only", "HEAD~1...HEAD"],
                    capture_output=True, text=True, cwd=self.repo_root
                )
                changed = result.stdout.strip().split("\n")
            except:
                changed = []
        
        return [f for f in changed if f and not f.startswith(".")]
    
    def analyze_java_controller(self, filepath: str) -> Dict:
        """Extract API endpoints from Java controller"""
        path = self.repo_root / filepath
        if not path.exists():
            return {}
        
        content = path.read_text()
        endpoints = []
        
        # Extract @RestController @RequestMapping
        class_match = re.search(r'@RequestMapping\("([^"]+)"\)', content)
        base_path = class_match.group(1) if class_match else "/api"
        
        # Extract @PostMapping, @GetMapping, @PutMapping, @DeleteMapping
        for match in re.finditer(
            r'@(Get|Post|Put|Delete|Patch)Mapping\("([^"]+)"\)\s+public\s+\w+\s+(\w+)\(',
            content
        ):
            method = match.group(1).upper()
            path_suffix = match.group(2)
            method_name = match.group(3)
            
            full_path = f"{base_path}{path_suffix}"
            endpoints.append({
                "method": method,
                "path": full_path,
                "handler": method_name,
                "class": Path(filepath).stem
            })
        
        return {"endpoints": endpoints, "filepath": filepath}
    
    def analyze_dotnet_controller(self, filepath: str) -> Dict:
        """Extract API endpoints from .NET controller"""
        path = self.repo_root / filepath
        if not path.exists():
            return {}
        
        content = path.read_text()
        endpoints = []
        
        # Extract [Route], [HttpGet], [HttpPost], etc.
        class_match = re.search(r'\[Route\("([^"]+)"\)\]', content)
        base_path = class_match.group(1) if class_match else "/api"
        
        # Extract [HttpGet], [HttpPost], [HttpPut], [HttpDelete], [HttpPatch]
        for match in re.finditer(
            r'\[Http(Get|Post|Put|Delete|Patch)\("([^"]*)"\)\]\s+public\s+\w+\s+(\w+)\(',
            content
        ):
            method = match.group(1).upper()
            path_suffix = match.group(2)
            method_name = match.group(3)
            
            if path_suffix:
                full_path = f"{base_path}/{path_suffix}"
            else:
                full_path = base_path
            
            endpoints.append({
                "method": method,
                "path": full_path,
                "handler": method_name,
                "class": Path(filepath).stem
            })
        
        return {"endpoints": endpoints, "filepath": filepath}
    
    def analyze_service(self, filepath: str) -> Dict:
        """Extract business logic methods from service"""
        path = self.repo_root / filepath
        if not path.exists():
            return {}
        
        content = path.read_text()
        methods = []
        
        # Java: public.*method_name
        for match in re.finditer(r'public\s+(\w+)\s+(\w+)\s*\(', content):
            return_type = match.group(1)
            method_name = match.group(2)
            if not method_name.startswith("get"):  # Skip getters
                methods.append({
                    "name": method_name,
                    "returns": return_type,
                    "language": "java"
                })
        
        # .NET: public.*MethodName
        for match in re.finditer(r'public\s+(\w+)\s+(\w+)\s*\(', content):
            return_type = match.group(1)
            method_name = match.group(2)
            if not method_name.startswith("Get"):  # Skip getters
                methods.append({
                    "name": method_name,
                    "returns": return_type,
                    "language": "dotnet"
                })
        
        return {
            "methods": methods,
            "filepath": filepath,
            "class": Path(filepath).stem
        }
    
    def analyze_features(self, filepath: str) -> Dict:
        """Extract test scenarios from Gherkin feature files"""
        path = self.repo_root / filepath
        if not path.exists():
            return {}
        
        content = path.read_text()
        scenarios = []
        feature_name = ""
        
        # Extract Feature name
        feature_match = re.search(r'Feature:\s*(.+)', content)
        if feature_match:
            feature_name = feature_match.group(1).strip()
        
        # Extract scenarios
        for match in re.finditer(r'Scenario:\s*(.+)', content):
            scenario_name = match.group(1).strip()
            scenarios.append(scenario_name)
        
        return {
            "feature": feature_name,
            "scenarios": scenarios,
            "count": len(scenarios),
            "filepath": filepath
        }
    
    def scan_changes(self):
        """Scan changed files for updates"""
        changes = {
            "java_controllers": [],
            "dotnet_controllers": [],
            "services": [],
            "features": [],
            "other": []
        }
        
        for filepath in self.changed_files:
            if "Controller.java" in filepath:
                analysis = self.analyze_java_controller(filepath)
                if analysis:
                    changes["java_controllers"].append(analysis)
                    self.updates.append(f"Java API: {filepath}")
            
            elif "Controller.cs" in filepath:
                analysis = self.analyze_dotnet_controller(filepath)
                if analysis:
                    changes["dotnet_controllers"].append(analysis)
                    self.updates.append(f".NET API: {filepath}")
            
            elif "Service.java" in filepath or "Service.cs" in filepath:
                analysis = self.analyze_service(filepath)
                if analysis:
                    changes["services"].append(analysis)
                    self.updates.append(f"Service logic: {filepath}")
            
            elif filepath.endswith(".feature"):
                analysis = self.analyze_features(filepath)
                if analysis:
                    changes["features"].append(analysis)
                    self.updates.append(f"Test scenarios: {filepath}")
            
            else:
                changes["other"].append(filepath)
        
        return changes
    
    def update_project_md(self, changes: Dict):
        """Update PROJECT.md with discovered changes"""
        if not self.project_md.exists():
            print(f"⚠️  PROJECT.md not found at {self.project_md}")
            return False
        
        content = self.project_md.read_text()
        updated = False
        
        # Update API Endpoints section (PART 2)
        if changes["java_controllers"] or changes["dotnet_controllers"]:
            content = self._update_api_endpoints(content, changes)
            updated = True
        
        # Update Service Logic (PART 3)
        if changes["services"]:
            content = self._update_service_logic(content, changes)
            updated = True
        
        # Update Test Coverage (PART 5)
        if changes["features"]:
            content = self._update_test_coverage(content, changes)
            updated = True
        
        # Add update timestamp
        content = self._add_update_timestamp(content)
        
        if updated:
            self.project_md.write_text(content)
            return True
        
        return False
    
    def _update_api_endpoints(self, content: str, changes: Dict) -> str:
        """Update API endpoints in PART 2"""
        java_endpoints = []
        for controller in changes["java_controllers"]:
            java_endpoints.extend(controller.get("endpoints", []))
        
        dotnet_endpoints = []
        for controller in changes["dotnet_controllers"]:
            dotnet_endpoints.extend(controller.get("endpoints", []))
        
        # Build update message
        if java_endpoints:
            update_text = "\n\n**[AUTO-UPDATE] Java endpoints detected:**\n"
            for ep in java_endpoints:
                update_text += f"- {ep['method']} {ep['path']} ({ep['handler']})\n"
            
            # Insert after Java section heading
            java_section = "#### **ProductController.java**"
            if java_section in content:
                idx = content.find(java_section)
                insert_pos = content.find("\n", idx) + 1
                content = content[:insert_pos] + update_text + content[insert_pos:]
        
        if dotnet_endpoints:
            update_text = "\n\n**[AUTO-UPDATE] .NET endpoints detected:**\n"
            for ep in dotnet_endpoints:
                update_text += f"- {ep['method']} {ep['path']} ({ep['handler']})\n"
            
            # Insert after .NET section heading
            dotnet_section = "#### **ProductController.cs**"
            if dotnet_section in content:
                idx = content.find(dotnet_section)
                insert_pos = content.find("\n", idx) + 1
                content = content[:insert_pos] + update_text + content[insert_pos:]
        
        return content
    
    def _update_service_logic(self, content: str, changes: Dict) -> str:
        """Update service logic in PART 3"""
        update_text = "\n\n**[AUTO-UPDATE] Service methods detected:**\n"
        
        for service in changes["services"]:
            update_text += f"\n**{service['class']}**:\n"
            for method in service.get("methods", [])[:5]:  # Limit to 5
                update_text += f"- {method['name']}() → {method['returns']}\n"
        
        # Insert in PART 3
        part3_marker = "## 🔗 PART 3: API Dependencies & Data Flows"
        if part3_marker in content:
            idx = content.find(part3_marker)
            insert_pos = content.find("\n", idx) + 1
            content = content[:insert_pos] + update_text + content[insert_pos:]
        
        return content
    
    def _update_test_coverage(self, content: str, changes: Dict) -> str:
        """Update test coverage in PART 5"""
        update_text = "\n\n**[AUTO-UPDATE] Feature scenarios detected:**\n"
        
        for feature in changes["features"]:
            update_text += f"\n**{feature['feature']}** ({feature['count']} scenarios):\n"
            for scenario in feature.get("scenarios", [])[:3]:  # Limit to 3
                update_text += f"- {scenario}\n"
        
        # Insert in PART 5
        part5_marker = "## 🧪 PART 5: Test Generation Strategy"
        if part5_marker in content:
            idx = content.find(part5_marker)
            insert_pos = content.find("\n", idx) + 1
            content = content[:insert_pos] + update_text + content[insert_pos:]
        
        return content
    
    def _add_update_timestamp(self, content: str) -> str:
        """Add timestamp of last update"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Update the timestamp in the file
        timestamp_pattern = r"Last Updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC"
        if re.search(timestamp_pattern, content):
            content = re.sub(timestamp_pattern, f"Last Updated: {timestamp}", content)
        else:
            # Add at the top after title
            content = content.replace(
                "*This file is the AI's memory of the project.",
                f"*Last Updated: {timestamp}*\n\n*This file is the AI's memory of the project."
            )
        
        return content
    
    def run(self) -> bool:
        """Execute the update process"""
        print(f"📋 Scanning for changes in {self.repo_root}...")
        print(f"   Changed files: {len(self.changed_files)}")
        
        if not self.changed_files:
            print("ℹ️  No changes detected")
            return False
        
        print(f"\n🔍 Analyzing changes...")
        changes = self.scan_changes()
        
        print(f"\n📝 Updates found:")
        for update in self.updates:
            print(f"   - {update}")
        
        if self.updates:
            print(f"\n✏️  Updating PROJECT.md...")
            if self.update_project_md(changes):
                print(f"✅ PROJECT.md updated successfully")
                return True
            else:
                print(f"⚠️  No updates made to PROJECT.md")
                return False
        
        return False


def main():
    auto_commit = "--auto-commit" in sys.argv
    
    updater = ProjectMindmapUpdater()
    updated = updater.run()
    
    if updated and auto_commit:
        print(f"\n📤 Auto-committing changes...")
        try:
            subprocess.run(
                ["git", "add", "PROJECT.md"],
                cwd=updater.repo_root,
                check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "[auto] update PROJECT.md with code changes"],
                cwd=updater.repo_root,
                check=True
            )
            print(f"✅ Changes committed")
        except subprocess.CalledProcessError as e:
            print(f"❌ Commit failed: {e}")
            return 1

    if not updated:
        # No controller/service/feature change to document (e.g. a .csproj-only or
        # config-only change). That is a normal no-op, not a failure — exit 0 so
        # the workflow doesn't go red.
        print("ℹ️  Nothing to update in PROJECT.md — skipping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
