from gateway import MainGateway
import helpers


def main():
    token = ""
    gateway = helpers.get_gateway()
    with open("token.txt") as token_file:
        token = token_file.read()
    if token != "":
        mainGateway = MainGateway(gateway, token)
        mainGateway.connect()


if __name__ == "__main__":
    main()
