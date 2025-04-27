import keyring
import getpass

# single-use file to set or delete a password to use with ChatGPT or Perplexity scraping
# the scraper code can automatically call the create_pwd function, or you can run the file directly
# includes the ability to set a password for Perplexity if adding login functionality is needed

def _get_username():
    username = input("Enter your username/email for this account: ")
    while username == '':
        username = input("Invalid. Enter your username/email for this account: ")
    
    return username

def create_pwd(username:str, service:str):
    if username == '':
        username = _get_username()

    password = getpass.getpass(f"Enter your password for '{username}' on {service.lower()} (input hidden): ")
    while password == '':
        password = getpass.getpass(f"Invalid. Enter your password for '{username}' on {service.lower()} (input hidden): ")

    keyring.set_password(service.lower(), username, password)
    print(f"{service.lower()} credentials saved securely.")

    return username

def _delete_pwd(username):
    service_to_del = input("Do you want to delete your password for <ChatGPT> or <Perplexity>? (enter one): ").lower()
    while not (service_to_del == 'chatgpt' or service_to_del == 'perplexity'):
        service_to_del = input("Invalid. Do you want to delete your password for <ChatGPT> or <Perplexity>? (enter one): ").lower()

    try:
        keyring.delete_password(service_to_del, username)
        print(f"{service_to_del} password for the username: '{username}' deleted from this environment successfully.")
        
    except:
        print(f"No password found for {service_to_del} with the username: '{username}'")

def prompt_user():
    service_name = input("Are you setting a password for <Perplexity> or <ChatGPT>? Or do you want to <delete> a password from this environment? (enter one): ").lower()

    if service_name == 'delete':
        _delete_pwd(_get_username())

    elif service_name == 'chatgpt' or service_name == 'perplexity':
        create_pwd(_get_username(), service_name)

    else:
        print ("Please enter 'ChatGPT' or 'Perplexity' to set a password, or 'delete' to delete a password.")

if __name__ == "__main__":
    prompt_user()