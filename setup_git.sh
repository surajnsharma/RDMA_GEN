#!/bin/bash
# Enable logging to a file
LOG_FILE="setup_git_repo.log"
exec &> >(tee -a "$LOG_FILE")

echo "Starting Git setup script..."

CONFIG_FILE=".git_config"
LARGE_FILE_SIZE=100000000  # 100 MB

initialize_git_repo() {
    if [ ! -d ".git" ]; then
        echo "No Git repository found. Initializing a new Git repository in this directory..."
        git init
        set_remote_url "push"
        echo "New Git repository initialized."
    else
        echo "Git repository already exists in this directory."
    fi
}

create_github_repo() {
    read -p "Enter the name for the new GitHub repository: " REPO_NAME
    read -p "Should the repo be public? (yes/no): " PUBLIC_CHOICE

    if [[ "$PUBLIC_CHOICE" =~ ^[Yy][Ee]?[Ss]?$ ]]; then
        VISIBILITY="--public"
    else
        VISIBILITY="--private"
    fi

    # Check if user is authenticated to GitHub CLI
    if ! gh auth status &>/dev/null; then
        echo "GitHub CLI not authenticated. Running 'gh auth login'..."
        gh auth login --hostname github.com --git-protocol ssh
    fi

    echo "Creating GitHub repository '$REPO_NAME'..."
    gh repo create "$REPO_NAME" $VISIBILITY --source=. --remote=origin --push

    if [ $? -eq 0 ]; then
        echo "✅ GitHub repository '$REPO_NAME' created and pushed successfully."
        echo "REPO_NAME=\"$REPO_NAME\"" >> "$CONFIG_FILE"
    else
        echo "❌ Failed to create GitHub repository."
        exit 1
    fi
}



set_remote_url() {
    if [ "$1" == "pull" ]; then
        REMOTE_URL="https://github.com/$GITHUB_USER/$REPO_NAME.git"
    else
        REMOTE_URL="git@github.com:$GITHUB_USER/$REPO_NAME.git"
    fi

    if git remote get-url origin &>/dev/null; then
        git remote set-url origin "$REMOTE_URL"
        echo "Remote URL updated to $REMOTE_URL"
    else
        git remote add origin "$REMOTE_URL"
        echo "Remote URL set to $REMOTE_URL"
    fi
}

delete_github_repo() {
    read -p "Enter your GitHub username: " GITHUB_USER
    read -p "Enter the name of the repository you want to delete: " REPO_NAME
    read -s -p "Enter your GitHub API token (with delete_repo permission): " GITHUB_TOKEN
    echo

    echo "Are you sure you want to delete the repository '$REPO_NAME' under user '$GITHUB_USER'?"
    read -p "Type 'DELETE' to confirm: " confirmation
    if [ "$confirmation" != "DELETE" ]; then
        echo "Deletion canceled."
        return 1
    fi

    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
        -H "Authorization: token $GITHUB_TOKEN" \
        "https://api.github.com/repos/$GITHUB_USER/$REPO_NAME")

    if [ "$RESPONSE" == "204" ]; then
        echo "The repository '$REPO_NAME' has been successfully deleted."
    elif [ "$RESPONSE" == "404" ]; then
        echo "Repository not found. Please check the username and repository name."
    elif [ "$RESPONSE" == "403" ]; then
        echo "Permission denied. Please ensure your API token has the 'delete_repo' permission."
    else
        echo "Failed to delete repository. HTTP response code: $RESPONSE"
    fi
}

delete_git_repo() {
    echo "Are you sure you want to delete the Git repository in this directory?"
    read -p "Type 'DELETE' to confirm: " confirmation
    if [ "$confirmation" == "DELETE" ]; then
        rm -rf .git
        if [ $? -eq 0 ]; then
            echo "The Git repository has been successfully deleted."
        else
            echo "Failed to delete the Git repository."
        fi
    else
        echo "Deletion canceled."
    fi
}

setup_ssh_key() {
    if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
        echo "Generating SSH key..."
        ssh-keygen -t ed25519 -C "$GITHUB_EMAIL" -f "$HOME/.ssh/id_ed25519" -q -N ""
        if [ $? -ne 0 ]; then
            echo "SSH key generation failed."
            exit 1
        fi
    else
        echo "SSH key already exists at ~/.ssh/id_ed25519"
    fi

    echo "Copy the SSH key below and add it to your GitHub account:"
    cat "$HOME/.ssh/id_ed25519.pub"
    read -p "Press Enter after adding the SSH key to GitHub..."

    mkdir -p ~/.ssh
    touch ~/.ssh/config

    if grep -q "Host github.com" ~/.ssh/config; then
        sed -i '' "/Host github.com/,+2d" ~/.ssh/config
    fi
    echo -e "Host github.com\n  IdentityFile ~/.ssh/id_ed25519\n  IdentitiesOnly yes" >> ~/.ssh/config
}

track_large_files_with_lfs() {
    echo "Checking for files larger than 100MB..."
    find . -type f -size +${LARGE_FILE_SIZE}c -not -path "./.git/*" | while read -r file; do
        echo "Tracking large file: $file"
        git lfs track "$file"
        git add .gitattributes "$file"
        git commit -m "Track large file $file with Git LFS"
    done
}

load_or_prompt_user_info() {
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
        echo "Current Git configuration:"
        echo "GitHub Username: $GITHUB_USER"
        echo "GitHub Email: $GITHUB_EMAIL"
        echo "Repository Name: $REPO_NAME"
        read -p "Type 'change' to update any of these values, or press Enter to continue.\nYour choice: " choice
    else
        choice="change"
    fi

    if [ "$choice" == "change" ] || [ -z "$GITHUB_USER" ] || [ -z "$GITHUB_EMAIL" ] || [ -z "$REPO_NAME" ]; then
        read -p "Enter your GitHub username: " GITHUB_USER
        read -p "Enter your GitHub email: " GITHUB_EMAIL
        read -p "Enter the name of the repository: " REPO_NAME
        echo "GITHUB_USER=\"$GITHUB_USER\"" > "$CONFIG_FILE"
        echo "GITHUB_EMAIL=\"$GITHUB_EMAIL\"" >> "$CONFIG_FILE"
        echo "REPO_NAME=\"$REPO_NAME\"" >> "$CONFIG_FILE"
    fi

    git config --global user.name "$GITHUB_USER"
    git config --global user.email "$GITHUB_EMAIL"
}

initialize_git_repo
load_or_prompt_user_info

echo "Choose an action:"
echo "1) Update (pull latest changes)"
echo "2) Push new changes (requires SSH access)"
echo "3) Delete the local Git repository"
echo "4) Delete Online Git repository"
echo "5) Create a new GitHub repository"
read -p "Enter your choice: " user_action

if [ "$user_action" == "1" ]; then
    set_remote_url "pull"
    git reset --hard
    git pull origin main
elif [ "$user_action" == "2" ]; then
    set_remote_url "push"
    setup_ssh_key
    track_large_files_with_lfs
    git add .
    git commit -m "Auto-commit: updating remote repository"
    git push origin main
elif [ "$user_action" == "3" ]; then
    delete_git_repo
elif [ "$user_action" == "4" ]; then
    delete_github_repo
elif [ "$user_action" == "5" ]; then
    create_github_repo
else
    echo "Invalid choice."
    exit 1
fi
