"""Configuração compartilhada de fixtures para os testes do engine."""
from __future__ import annotations

import sys
from pathlib import Path

# Garante que o pacote `engine` seja importável quando os testes rodam a
# partir de qualquer diretório de trabalho.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
