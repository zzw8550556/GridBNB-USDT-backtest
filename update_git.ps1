# PowerShell script to update Git repository

# Remove .env from Git tracking without deleting the file
git rm --cached .env

# Add all other changes
git add .

# Commit the changes
git commit -m "添加.gitignore和.env.example示例文件"

# Push to GitHub
git push

Write-Host "已完成Git操作。按任意键退出..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
