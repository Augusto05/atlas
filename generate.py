import streamlit_authenticator as stauth

# Senha original
senha = "B4b@2024!"

# Gera hash
hashed = stauth.Hasher([senha]).generate()

# Exibe resultado
print("Senha original:", senha)
print("Hash gerado:", hashed[0])
