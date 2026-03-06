import requests

headers = {
    "api-key": "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"
}

r = requests.get(
    "https://api.brevo.com/v3/account",
    headers=headers
)

print(r.status_code)
print(r.text)