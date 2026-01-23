## Cloud vs Public Repository Workflow

This project is maintained in two forms:

* **Cloud (Private)** — full-featured version with private logic

* **Public (OSS)** — open-source version with sensitive parts removed

👉 **The private repository is the single source of truth.**

---

## **Repository Overview**

| Repository | Purpose |
| :---- | :---- |
| ProductPathPro-cloud | Private / cloud version |
| ProductPathPro | Public / open-source version |

---

## **File Naming Conventions**

### **Private-only files**

Private functionality lives in files ending with:

`*_cloud.*`

**Examples**

`views_cloud.py`  
`settings_cloud.py`  
`billing_cloud.js`

These files:

* Exist **only** in the private repository

* Are **automatically removed** during public export

* **Never appear** in the OSS repository

---

### **Public (OSS) files**

Public files use standard filenames:

`views.py`  
`settings.py`  
`billing.js`

These files:

* Are safe for open-source

* Appear in **both** repositories

---

### **OSS-only ignored files**

Some files are ignored by `.gitignore` in the private repo but **must exist in the OSS repo**.

**Example**

`static/js/main.js`

Important clarifications:

* These files **exist physically in the private working directory**

* They may be ignored by git in the private repo

* During export, they are **force-added** to the public repo

* They are listed explicitly in the export script:

`$OSSFiles = @(`  
    `"static/js/main.js"`  
`)`

⚠ These files **do not generate individual commits**.  
 They are included in the **single generated OSS commit**.

---

## **Development Rules (Very Important)**

✅ **Always develop in the private repo**

* Add features

* Fix bugs

* Refactor

* Review PRs

🚫 **Never develop directly in the public repo**

The public repository is **generated**, not authored.

---

## **Exporting to Public (OSS)**

### **When to export**

Export only after:

* A feature is finished

* Sensitive logic is isolated in `*_cloud` files

* Code is reviewed and stable

---

### **Export steps**

From your **local development machine** (never production):

`.\Export-Public.ps1`

---

### **What happens automatically**

* Private repo is cloned fresh

* All `*_cloud.*` files are removed

* OSS-only ignored files are added

* A **single clean commit** is created

* Public repo is **force-pushed**

---

## **Git History & Authors**

* Public history is **rewritten**

* Public repo contains **one generated commit per export**

* Commit author is the exporter (script runner)

* Original authorship is preserved **only in private repo**

This is **intentional and correct** for OSS sanitization.

---

## **Why this approach is used**

### **❌ Why not folders like `/private` or `/cloud`?**

* Django imports break

* Folder-specific conditionals leak into code

* Repo structures diverge

* Refactoring becomes painful

---

### **✅ Why filename-based separation works**

* Same folder structure everywhere

* Clean imports

* Easy filtering

* Zero runtime branching

* Extremely hard to leak private code accidentally

---

## **Mental Model (Critical)**

`Private repo = source code`  
`Public repo  = build artifact`

You do **not** edit the public repo.  
 You **generate** it.

---

## **Recommended Safety Practices**

✔ Run export only on dev machine  
 ✔ Treat public repo as read-only  
 ✔ Review public diff after export  
 ✔ Never merge public → private  
 ✔ Treat generated history as disposable

---

## **Summary**

* Private repo owns the truth

* `_cloud` files contain private logic

* Public repo is auto-generated

* One script controls everything

* Safe, scalable, professional workflow

---

## **Public version deploy instructions**

Git authentication setup (Windows)

To prevent Git from asking for a token every time, run the following command:

`git config --global credential.helper manager`

### Running the export script

The script must be executed from PowerShell on Windows:

`.\Export-Public.ps1`

Script content:

```
# ===============================
# Export-Public-Automatic-Clean.ps1
# ===============================
$PrivateRepo     = "https://github.com/Hymetry/ProductPathPro-cloud.git"
$PublicRepo      = "https://github.com/Hymetry/ProductPathPro.git"
$PrivateWorkDir  = "C:\tmp8\ProductPathPro-cloud"
$ExportDir       = "C:\tmp8\ProductPathPro"

$OSSFiles = @(
    "static/js/main.js"
)

# 1. Clean Export Directory
if (Test-Path $ExportDir) {
    Write-Host "Clearing existing export directory..."
    Remove-Item -Recurse -Force $ExportDir
}
New-Item -ItemType Directory -Path $ExportDir | Out-Null

# 2. Clone Private Repo
Write-Host "Cloning private repo..."
git clone $PrivateRepo $ExportDir
Set-Location $ExportDir

# 3. SEVER PRIVATE HISTORY
# This removes the link to your private commits/logs
Write-Host "Removing private git history..."
if (Test-Path ".git") {
    Remove-Item -Path ".git" -Recurse -Force
}

# 4. PHYSICAL PURGE of *_cloud* files
# This handles root files (manage_cloud.py) and subfolder files
Write-Host "Purging all *_cloud* files/folders..."
Get-ChildItem -Path . -Filter "*_cloud*" -Recurse | Remove-Item -Force -Recurse

# 5. Copy OSS-only files from your local working copy
foreach ($f in $OSSFiles) {
    $SourcePath = Join-Path $PrivateWorkDir $f
    $TargetPath = Join-Path $ExportDir $f

    if (Test-Path $SourcePath) {
        Write-Host "Copying OSS-only file: $f"
        New-Item -ItemType Directory -Force -Path (Split-Path $TargetPath) | Out-Null
        Copy-Item $SourcePath $TargetPath -Force
    }
}

# 6. Initialize as NEW Public Repo
Write-Host "Initializing clean public repository..."
git init -b main
git add .
git commit -m "Generate public OSS version"

# 7. Push to Public
Write-Host "Pushing to public repo..."
git remote add public $PublicRepo
git push public main --force

Write-Host "Done! Public repo is now a clean 'Squashed' version of the private repo."
```
