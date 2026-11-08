# rtx5090-monitor for Windows

The setup guide, configuration, usage and troubleshooting are in the main README:

- [Windows installation](../README.md#windows-installation): HWiNFO64 setup, install, checks
- [Configuration](../README.md#configuration-windows): `config.json` keys
- [Using it](../README.md#using-it), [Safety notes](../README.md#safety-notes), [Troubleshooting](../README.md#troubleshooting)

Quick reference:

```powershell
python astral-guard.py --list-sensors        # which HWiNFO Gadget entries became pins
python astral-guard.py [--json]              # one check; exit 0/1/2/3 = OK/WARNING/CRITICAL/UNKNOWN
python astral-guard.py --daemon [--dry-run]  # background guard (install.ps1 starts it at sign-in)
python gpu-monitor.py                        # terminal dashboard
python -m unittest discover -s tests         # rule tests against astral-guard's corpus
powershell -ExecutionPolicy Bypass -File install.ps1     # / uninstall.ps1 [-Purge]
```
