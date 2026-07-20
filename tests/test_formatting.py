from engine.formatting import formatar_brl, formatar_numero


def test_formatar_numero_milhar_e_decimal():
    assert formatar_numero(1234.5, 1) == "1.234,5"


def test_formatar_numero_sem_casas_decimais():
    assert formatar_numero(1234, 0) == "1.234"


def test_formatar_numero_sem_milhar():
    assert formatar_numero(9.87, 2) == "9,87"


def test_formatar_numero_negativo():
    assert formatar_numero(-1234.5, 1) == "-1.234,5"


def test_formatar_brl():
    assert formatar_brl(1234567.0, 0) == "R$ 1.234.567"
