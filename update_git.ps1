# PowerShell script to update Git repository

# Remove .env from Git tracking without deleting the file
git rm --cached .env

# Add all other changes
git add .

# Commit the changes
git commit -m "Add .gitignore and remove .env from tracking"

# Push to GitHub
git push

Write-Host "Git operations completed. Press any key to exit..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
