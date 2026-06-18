# Mission: Convertire MKV per Logitech Z906

## M1: Preparazione e verifica
### T1.1: Verifica ambiente | agent:Commander | status:completed
- [x] S1.1.1: Verificare FFmpeg installato
- [x] S1.1.2: Verificare encoder AC3 disponibile
- [x] S1.1.3: Verificare GitHub remote

### T1.2: Contestualizzazione | agent:Commander | status:completed
- [x] S1.2.1: Leggere script e documentazione
- [x] S1.2.2: Salvare context.md

## M2: Esecuzione conversione
### T2.1: Input utente | agent:Commander | status:pending
- [ ] S2.1.1: Chiedere all'utente la directory con gli MKV
- [ ] S2.1.2: Verificare che la directory contenga file .mkv

### T2.2: Conversione | agent:Worker | status:pending | depends:T2.1
- [ ] S2.2.1: Eseguire mk-downmix.py sulla directory indicata
- [ ] S2.2.2: Verificare output file generati

### T2.3: Verifica finale | agent:Reviewer | status:pending | depends:T2.2
- [ ] S2.3.1: Verificare tracce audio nei file output
- [ ] S2.3.2: Confermare conversione completata
