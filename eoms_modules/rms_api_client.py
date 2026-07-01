import requests


class RMSApiClient:
    def __init__(self):
        self.session = requests.Session()

        # 🔥 YOUR REAL COOKIES (from what you pasted)
        self.session.cookies.update({
            "rms_session": "eyJpdiI6InpSVG05ZHpneXRESjBObnNDNUtEcnc9PSIsInZhbHVlIjoiS3ZjUURZNkRBUXQwbTQ1Tkx1aXZRTWZha3g1S3hIazdaa1JZa01RVGsrMFpWeVhlRi9BNGRkV3lTQWQxK0VWQnlLVTV0S0dQT0FkcWQ0UUxZOFNLV29PZklOZ091cVU0eU5sUURtbzJhYXpFV3U5NENtNENVOEMzdmx4OFhrWisiLCJtYWMiOiJmMjgwNzJlYmIzYjE0OWQ0YThlZWU2ZmUxYmQ3ZmRiYzRiYzU3ZTM0NDMyNGY4MDIwYzUzMDJlMjVhOWMxYWVhIiwidGFnIjoiIn0=",
            "XSRF-TOKEN": "eyJpdiI6Ii8rR3VJOUJrVUJMTnU4dGVaU2crQ3c9PSIsInZhbHVlIjoidUNXaXVhNUcxYUdLeXp3ZWlhWGxZV0c3SWJ4dUk4dG4yd0RuOXU0d3BGQ1JSamNkUUd0RENVQ2t2SU9ac29ncHNpNmhVYVIrWSt3aFNyR3g1WjJSWUZPTGV4UlJsMDVkTTF4NmM5eU9sWEVRVWltaVJRKzA5d1FZNTRNMFBGZ0oiLCJtYWMiOiJiN2NjNTJkZWZmOTgxZTI1MmFiNjk2OWMzN2RlOWZkODVkZTk1MDdlNTBmZTA1NTlmNjQ0ZDJkNDU0NWI4NGIzIiwidGFnIjoiIn0="
        })

        # 🔥 HEADER TOKEN (this is REQUIRED separately)
        self.xsrf = "eyJpdiI6Ii8rR3VJOUJrVUJMTnU4dGVaU2crQ3c9PSIsInZhbHVlIjoidUNXaXVhNUcxYUdLeXp3ZWlhWGxZV0c3SWJ4dUk4dG4yd0RuOXU0d3BGQ1JSamNkUUd0RENVQ2t2SU9ac29ncHNpNmhVYVIrWSt3aFNyR3g1WjJSWUZPTGV4UlJsMDVkTTF4NmM5eU9sWEVRVWltaVJRKzA5d1FZNTRNMFBGZ0oiLCJtYWMiOiJiN2NjNTJkZWZmOTgxZTI1MmFiNjk2OWMzN2RlOWZkODVkZTk1MDdlNTBmZTA1NTlmNjQ0ZDJkNDU0NWI4NGIzIiwidGFnIjoiIn0="

    def authorize(self):
        url = "https://rms.reusability.com/api/authorization/route"

        return self.session.get(
            url,
            params={"route_name": "LadingBills"},
            headers={"x-xsrf-token": self.xsrf}
        )

    def fetch(self, page=1):
        # STEP 1: auth handshake
        self.authorize()

        # STEP 2: real data call
        url = "https://rms.reusability.com/bills-of-lading-report"

        response = self.session.get(
            url,
            params={"page": page, "limit": 20},
            headers={"x-xsrf-token": self.xsrf}
        )

        print("\nSTATUS:", response.status_code)
        print("CONTENT START:\n", response.text[:200])

        try:
            return response.json()
        except:
            print("❌ STILL NOT JSON (SESSION ISSUE OR WRONG ROUTE FLOW)")
            return None