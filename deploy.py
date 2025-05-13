import os
import re
import subprocess

from colorama import Fore, init

init(autoreset=True)


def set_permissions(dir_path):
    print(Fore.CYAN + "\nSetting ownership and permissions for project directory...")

    try:
        # Change ownership to www-data
        subprocess.run(["sudo", "chown", "-R", "www-data:www-data", dir_path], check=True)

        # Give owner (www-data) full access; group and others: read + execute
        subprocess.run(["sudo", "chmod", "-R", "750", dir_path], check=True)

        # Specifically ensure manage.py is executable
        subprocess.run(["sudo", "chmod", "+x", f"{dir_path}/manage.py"], check=True)

        print(Fore.GREEN + "Permissions set successfully.")
    except subprocess.CalledProcessError as e:
        print(Fore.RED + f"Error setting permissions: {e}")


def ask_variable(prompt, validation_fn=None, default_value=None):
    while True:
        user_input = input(
            Fore.BLUE + f"{prompt} ({'default: ' + default_value if default_value else 'required'}): ").strip()

        if not user_input and default_value:
            user_input = default_value

        if validation_fn:
            if not validation_fn(user_input):
                print(Fore.RED + "Invalid input. Please try again.")
                continue

        return user_input


# Validate if the input is a valid GitHub URL (optional)
def validate_github_url(url):
    if url == "":
        return True  # Empty input is allowed
    pattern = r"^(https?://)?(www\.)?github\.com/[\w-]+/[\w-]+(\.git)?$"
    return bool(re.match(pattern, url))


# Validate if the project folder name is valid
def validate_project_folder(folder):
    return bool(re.match(r'^[\w-]+$', folder))


# Project details
project_name = ask_variable("Enter the project name", validate_project_folder)
project_user = ask_variable("Enter the database username", default_value="myprojectuser")
password = ask_variable("Enter the database password", default_value="password")
domains = ask_variable("Enter domain names (e.g. website.com www.website.com)")
staticfiles_folder_name = ask_variable("Enter static files folder name", default_value="static")
mediafiles_folder_name = ask_variable("Enter media files folder name", default_value="media")

# Gunicorn socket file name
socket_name = ask_variable("Enter Gunicorn socket file name (without .sock)", default_value="gunicorn")
socket_path = f"/run/{socket_name}.sock"

# Project directory path
project_dir = ask_variable("Enter the project directory name", validate_project_folder)
project_dir_path = f"/home/{project_dir}"
requirements_path = f"{project_dir_path}/requirements.txt"

# GitHub repo URL (optional)
github_url = ask_variable("Enter the GitHub repository URL (press Enter to skip)", validate_github_url)

if not os.path.exists(project_dir_path):
    os.mkdir(project_dir_path)

if not os.path.exists(f'{project_dir_path}/static'):
    os.mkdir(f'{project_dir_path}/static')

if not os.path.exists(f'{project_dir_path}/media'):
    os.mkdir(f'{project_dir_path}/media')

# Clone GitHub repo if URL is provided
if github_url:
    print(Fore.CYAN + f"Cloning from {github_url}...")
    try:
        subprocess.run(["git", "clone", github_url, project_dir_path], check=True)
    except subprocess.CalledProcessError:
        print(Fore.RED + "Error while cloning the repository. Please check the URL.")

# Virtual environment and WSGI app
venv_dir = ".venv"
wsgi_app = f"{project_name}.wsgi:application"


# Setting up PostgreSQL database
def setup_postgresql():
    print(Fore.CYAN + "\nSetting up PostgreSQL database...")
    # Running commands to create the database and user
    subprocess.run(["sudo", "-u", "postgres", "psql", "-c", f"CREATE DATABASE {project_name};"], check=True)
    subprocess.run(["sudo", "-u", "postgres", "psql", "-c", f"CREATE USER {project_user} WITH PASSWORD '{password}';"],
                   check=True)
    subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-c", f"ALTER ROLE {project_user} SET client_encoding TO 'utf8';"],
        check=True)
    subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
                    f"ALTER ROLE {project_user} SET default_transaction_isolation TO 'read committed';"], check=True)
    subprocess.run(["sudo", "-u", "postgres", "psql", "-c", f"ALTER ROLE {project_user} SET timezone TO 'UTC';"],
                   check=True)
    subprocess.run(
        ["sudo", "-u", "postgres", "psql", "-c", f"GRANT ALL PRIVILEGES ON DATABASE {project_name} TO {project_user};"],
        check=True)


# Create virtual environment
def create_virtualenv():
    print(Fore.CYAN + "\nCreating virtual environment...")
    subprocess.run(["python3", "-m", "venv", f"{project_dir_path}/{venv_dir}"], check=True)
    if os.path.exists(requirements_path):
        subprocess.run([f"{project_dir_path}/{venv_dir}/bin/pip", "install", "-r", requirements_path], check=True)
    else:
        print(Fore.RED + "requirements.txt not found. Skipping installation of dependencies.")


# Run Django migrations
def run_migrations():
    print(Fore.CYAN + "\nRunning Django migrations...")
    subprocess.run([f"{project_dir_path}/{venv_dir}/bin/python", "manage.py", "makemigrations"], cwd=project_dir_path)
    subprocess.run([f"{project_dir_path}/{venv_dir}/bin/python", "manage.py", "migrate"], cwd=project_dir_path)


# Collect static files
def collect_static_files():
    print(Fore.CYAN + "\nCollecting static files...")
    subprocess.run([f"{project_dir_path}/{venv_dir}/bin/python", "manage.py", "collectstatic", "--noinput"],
                   cwd=project_dir_path, check=True)


# Gunicorn setup (socket and service files)
def setup_gunicorn():
    print(Fore.CYAN + "\nSetting up Gunicorn...")

    # Gunicorn socket
    socket_file = f"/etc/systemd/system/{project_name}.socket"
    with open(socket_file, 'w') as f:
        f.write(f"""
[Unit]
Description=gunicorn socket

[Socket]
ListenStream={socket_path}

[Install]
WantedBy=sockets.target
""")

    # Gunicorn service
    service_file = f"/etc/systemd/system/{project_name}.service"
    with open(service_file, 'w') as f:
        f.write(f"""
[Unit]
Description=gunicorn daemon
Requires={project_name}.socket
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory={project_dir_path}
ExecStart={project_dir_path}/{venv_dir}/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:{socket_path} \
          {wsgi_app}

[Install]
WantedBy=multi-user.target
""")


# Nginx setup
def setup_nginx():
    print(Fore.CYAN + "\nSetting up Nginx...")
    nginx_config = f"""
server {{
    listen 80;
    server_name {' '.join(domains.split(" "))};

    location = /favicon.ico {{ access_log off; log_not_found off; }}
    location /static/ {{
        alias {project_dir_path}/{staticfiles_folder_name}/;
    }}
    location /media/ {{
        alias {project_dir_path}/{mediafiles_folder_name}/;
    }}

    location / {{
        include proxy_params;
        proxy_pass http://unix:{socket_path};
    }}
}}
"""
    # Write Nginx configuration to file
    nginx_file = f"/etc/nginx/sites-available/{project_name}"
    with open(nginx_file, 'w') as f:
        f.write(nginx_config)

    # Enable site and restart Nginx
    enabled_path = f"/etc/nginx/sites-enabled/{project_name}"
    if os.path.exists(enabled_path):
        subprocess.run(["sudo", "rm", enabled_path], check=True)
    subprocess.run(["sudo", "ln", "-s", nginx_file, enabled_path], check=True)
    subprocess.run(["sudo", "systemctl", "restart", "nginx"], check=True)


# Firewall settings
def configure_firewall():
    print(Fore.CYAN + "\nConfiguring firewall...")
    subprocess.run(["sudo", "ufw", "delete", "allow", "8000"], check=False)
    subprocess.run(["sudo", "ufw", "allow", "Nginx Full"], check=True)


# Finalize the process
def finalize():
    print(Fore.GREEN + "\nDeployment successful! Remember to visit the site and check logs if there are any errors.")
    subprocess.run(["sudo", "systemctl", "start", f"{project_name}.socket"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", f"{project_name}.socket"], check=True)
    subprocess.run(["sudo", "systemctl", "start", "nginx"], check=True)
    subprocess.run(["sudo", "systemctl", "enable", "nginx"], check=True)


# Run the deployment process
if __name__ == "__main__":
    # Ask for user input
    setup_postgresql()
    create_virtualenv()
    run_migrations()
    collect_static_files()
    setup_gunicorn()
    setup_nginx()
    configure_firewall()
    finalize()
    set_permissions(dir_path=project_dir_path)
