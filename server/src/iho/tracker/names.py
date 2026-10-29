"""Nome de exibicao de pessoa.

O tracker identifica todo mundo por e-mail. Nome e so enfeite, e chega sujo de
duas formas pelo cabecalho do Authentik:

- a conta admin padrao ("authentik Default Admin"), que nao e nome de ninguem;
- UTF-8 lido como latin-1 ("Victor SÃ¡" em vez de "Victor Sá").

Nome que nao se salva vira None, e a interface mostra o e-mail.
"""


def clean_person_name(name: str | None) -> str | None:
    if name is None:
        return None
    name = name.strip()
    if not name or name.lower().startswith("authentik"):
        return None
    if "Ã" in name or "Â" in name:
        try:
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name or None
