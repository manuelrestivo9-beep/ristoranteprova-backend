import os
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel, field_validator
from datetime import datetime, date
import calendar

# --- 1. CONFIGURAZIONE DATABASE ---
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")
if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError(
        "Variabile d'ambiente DATABASE_URL mancante. Impostala su Render "
        "(Environment) con la stringa di connessione al database Postgres."
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

ORARI_VALIDI = ["12:30", "13:00", "13:30", "19:00", "19:30", "20:00", "20:30", "21:00"]
AREE_VALIDE = ["Ristorante", "Pizzeria", "Misto"]

class Prenotazione(Base):
    __tablename__ = "prenotazioni"
    id = Column(Integer, primary_key=True, index=True)
    nome_cliente = Column(String, index=True)
    telefono = Column(String)
    data_prenotazione = Column(String, index=True)
    ora_prenotazione = Column(String)
    numero_persone = Column(Integer)
    note = Column(String, default="")
    numero_tavolo = Column(String, default="Da assegnare")
    area = Column(String)

Base.metadata.create_all(bind=engine)

class PrenotazioneCreate(BaseModel):
    nome_cliente: str
    telefono: str
    data_prenotazione: str
    ora_prenotazione: str
    numero_persone: int
    note: str = ""
    area: str

    @field_validator("numero_persone")
    @classmethod
    def persone_valide(cls, v):
        if v <= 0:
            raise ValueError("Il numero di persone deve essere maggiore di zero.")
        if v > 40:
            raise ValueError("Per gruppi superiori a 40 persone contatta direttamente il locale.")
        return v

    @field_validator("ora_prenotazione")
    @classmethod
    def orario_valido(cls, v):
        if v not in ORARI_VALIDI:
            raise ValueError(f"Orario non valido. Orari disponibili: {', '.join(ORARI_VALIDI)}")
        return v

    @field_validator("area")
    @classmethod
    def area_valida(cls, v):
        if v not in AREE_VALIDE:
            raise ValueError(f"Area non valida. Aree disponibili: {', '.join(AREE_VALIDE)}")
        return v

    @field_validator("data_prenotazione")
    @classmethod
    def data_valida(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Data non valida, usa il formato AAAA-MM-GG.")
        return v

class AssegnaTavolo(BaseModel):
    numero_tavolo: str

# --- 2. CONFIGURAZIONE MOTORE E SICUREZZA ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Chiave segreta per proteggere le rotte riservate allo staff.
# IMPORTANTE: impostala come variabile d'ambiente su Render (Environment -> STAFF_API_KEY)
# con un valore lungo e casuale. Se non la imposti, il server si rifiuta di partire
# per evitare di girare senza protezione.
STAFF_API_KEY = os.getenv("STAFF_API_KEY")
if not STAFF_API_KEY:
    raise RuntimeError(
        "Variabile d'ambiente STAFF_API_KEY mancante. Impostala su Render "
        "(Environment) con una chiave segreta a scelta."
    )

def verifica_staff(x_staff_key: str = Header(default=None)):
    if x_staff_key != STAFF_API_KEY:
        raise HTTPException(status_code=401, detail="Accesso non autorizzato.")

# --- 3. LE ROTTE ---

@app.post("/prenotazioni/")
def crea_prenotazione(prenotazione: PrenotazioneCreate, db: Session = Depends(get_db)):
    adesso = datetime.now()
    data_di_oggi = adesso.strftime("%Y-%m-%d")
    ora_attuale = adesso.hour

    if prenotazione.data_prenotazione < data_di_oggi:
        raise HTTPException(status_code=400, detail="Non è possibile prenotare per una data passata.")

    if prenotazione.data_prenotazione == data_di_oggi and ora_attuale >= 18:
        raise HTTPException(status_code=400, detail="Le prenotazioni web per stasera sono chiuse. Chiamaci al locale.")

    prenotazioni_giorno = db.query(Prenotazione).filter(
        Prenotazione.data_prenotazione == prenotazione.data_prenotazione,
        Prenotazione.area == prenotazione.area
    ).all()

    totale_giornaliero = sum([p.numero_persone for p in prenotazioni_giorno])

    if prenotazione.area == "Ristorante" and (totale_giornaliero + prenotazione.numero_persone) > 80:
        raise HTTPException(status_code=400, detail="Il Ristorante è completamente pieno per questa data.")
    if prenotazione.area == "Pizzeria" and (totale_giornaliero + prenotazione.numero_persone) > 150:
        raise HTTPException(status_code=400, detail="La Pizzeria è completamente piena per questa data.")
    if prenotazione.area == "Misto" and (totale_giornaliero + prenotazione.numero_persone) > 50:
        raise HTTPException(status_code=400, detail="Il limite per i tavoli Misti è stato raggiunto per questa data.")

    prenotazioni_ora = [p for p in prenotazioni_giorno if p.ora_prenotazione == prenotazione.ora_prenotazione]
    totale_orario = sum([p.numero_persone for p in prenotazioni_ora])

    if prenotazione.area == "Ristorante" and (totale_orario + prenotazione.numero_persone) > 20:
        raise HTTPException(status_code=400, detail=f"L'orario delle {prenotazione.ora_prenotazione} per il Ristorante è al completo.")
    if prenotazione.area == "Pizzeria" and (totale_orario + prenotazione.numero_persone) > 50:
        raise HTTPException(status_code=400, detail=f"L'orario delle {prenotazione.ora_prenotazione} per la Pizzeria è al completo.")
    if prenotazione.area == "Misto" and (totale_orario + prenotazione.numero_persone) > 15:
        raise HTTPException(status_code=400, detail=f"L'orario delle {prenotazione.ora_prenotazione} per i tavoli Misti è al completo.")

    nuova_prenotazione = Prenotazione(**prenotazione.model_dump())
    db.add(nuova_prenotazione)
    db.commit()
    db.refresh(nuova_prenotazione)
    return nuova_prenotazione

@app.post("/prenotazioni/staff/")
def crea_prenotazione_staff(
    prenotazione: PrenotazioneCreate,
    db: Session = Depends(get_db),
    _: None = Depends(verifica_staff),
):
    nuova_prenotazione = Prenotazione(**prenotazione.model_dump())
    db.add(nuova_prenotazione)
    db.commit()
    db.refresh(nuova_prenotazione)
    return nuova_prenotazione

@app.get("/prenotazioni/")
def leggi_prenotazioni(db: Session = Depends(get_db), _: None = Depends(verifica_staff)):
    return db.query(Prenotazione).all()

@app.delete("/prenotazioni/{prenotazione_id}")
def elimina_prenotazione(
    prenotazione_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(verifica_staff),
):
    prenotazione = db.query(Prenotazione).filter(Prenotazione.id == prenotazione_id).first()
    if prenotazione is None:
        raise HTTPException(status_code=404, detail="Prenotazione non trovata")

    db.delete(prenotazione)
    db.commit()
    return {"messaggio": f"Prenotazione #{prenotazione_id} cancellata!"}

@app.put("/prenotazioni/{prenotazione_id}/tavolo")
def assegna_tavolo(
    prenotazione_id: int,
    dati: AssegnaTavolo,
    db: Session = Depends(get_db),
    _: None = Depends(verifica_staff),
):
    prenotazione = db.query(Prenotazione).filter(Prenotazione.id == prenotazione_id).first()
    if prenotazione is None:
        raise HTTPException(status_code=404, detail="Prenotazione non trovata")

    if dati.numero_tavolo != "Da assegnare":
        conflitto = db.query(Prenotazione).filter(
            Prenotazione.id != prenotazione_id,
            Prenotazione.data_prenotazione == prenotazione.data_prenotazione,
            Prenotazione.ora_prenotazione == prenotazione.ora_prenotazione,
            Prenotazione.numero_tavolo == dati.numero_tavolo,
        ).first()
        if conflitto is not None:
            raise HTTPException(
                status_code=400,
                detail=f"Il tavolo {dati.numero_tavolo} è già assegnato a {conflitto.nome_cliente} per lo stesso giorno e orario."
            )

    prenotazione.numero_tavolo = dati.numero_tavolo
    db.commit()
    return {"messaggio": "Tavolo aggiornato con successo!"}

@app.get("/orari-validi/")
def orari_validi():
    return {"orari": ORARI_VALIDI}

# --- ROTTE PER IL CALENDARIO ---

@app.get("/disponibilita-mese/")
def disponibilita_mese(anno: int, mese: int, area: str, db: Session = Depends(get_db)):
    _, num_days = calendar.monthrange(anno, mese)
    giorni = []
    oggi = date.today()

    for d in range(1, num_days + 1):
        data_corrente = date(anno, mese, d)
        if data_corrente < oggi:
            giorni.append({"giorno": data_corrente.strftime("%Y-%m-%d"), "disponibile": False})
        else:
            giorni.append({"giorno": data_corrente.strftime("%Y-%m-%d"), "disponibile": True})

    return {"giorni": giorni}

LIMITE_ORARIO = {"Ristorante": 20, "Pizzeria": 50, "Misto": 15}

@app.get("/disponibilita-giorno/")
def disponibilita_giorno(data: str, area: str, db: Session = Depends(get_db)):
    adesso = datetime.now()
    data_di_oggi = adesso.strftime("%Y-%m-%d")

    if data == data_di_oggi and adesso.hour >= 18:
        return {"chiuso": True, "slot": []}

    if area not in LIMITE_ORARIO:
        raise HTTPException(status_code=400, detail="Area non valida.")

    limite = LIMITE_ORARIO[area]

    prenotazioni_giorno = db.query(Prenotazione).filter(
        Prenotazione.data_prenotazione == data,
        Prenotazione.area == area,
    ).all()

    occupati_per_ora = {}
    for p in prenotazioni_giorno:
        occupati_per_ora[p.ora_prenotazione] = occupati_per_ora.get(p.ora_prenotazione, 0) + p.numero_persone

    slot = []
    for o in ORARI_VALIDI:
        occupati = occupati_per_ora.get(o, 0)
        posti_rimasti = max(limite - occupati, 0)
        slot.append({
            "ora": o,
            "disponibile": posti_rimasti > 0,
            "posti_rimasti": posti_rimasti,
        })

    return {"chiuso": False, "slot": slot}

# --- 4. AVVIO SERVER ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)