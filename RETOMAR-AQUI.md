# Retomar aqui — mcp-servers

> Escrito el **9-sep-2026** leyendo el repositorio.
> **No transcribe git**: para el estado corriente mandan `git log` y `git status`, que nunca
> se pudren. Aqui va solo lo que el codigo **no** dice. Criterio de cada linea: *si la quito,
> quien retome comete un error que de otro modo no cometeria*.
> **(deducido)** = lectura mia, no hecho verificado.

## Que es
Cuatro servidores MCP para Claude Code, con pruebas de guardia (`tests/`).

## Lo que el codigo no dice
- Hubo una **inyeccion de shell en `vps-monitor`**, arreglada, y **hay una prueba que existe
  para que no vuelva**. Si esa prueba te estorba, el problema es tu cambio.
- Las pruebas son de guardia, no de cobertura: cada una encierra algo que si se cae deja el
  servidor funcionando igual de bien y mintiendo.
