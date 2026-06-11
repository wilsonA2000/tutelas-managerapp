# P6 — Publicar el OAuth de Gmail a Production (acción de Wilson, ~5 min)

**Por qué**: la app OAuth está en modo *Testing* → Google **revoca el refresh token a los 7 días**.
Eso fue lo que dejó la plataforma ciega del 4 al 10 de junio de 2026 ("No hay emails nuevos"
mientras el token estaba muerto). En *Production* el token no expira por tiempo.

## Pasos

1. Entrar a https://console.cloud.google.com/ con la cuenta dueña del proyecto OAuth
   (la que creó `gmail_credentials.json` — revisar el `client_id` dentro del archivo si hay duda).
2. Seleccionar el proyecto correcto (arriba a la izquierda).
3. Menú ☰ → **APIs y servicios** → **Pantalla de consentimiento de OAuth**.
4. En "Estado de publicación" aparecerá **En prueba (Testing)** → botón **PUBLICAR APLICACIÓN**.
5. Confirmar. Como la app solo usa scopes de Gmail con tu propia cuenta, **no requiere
   verificación de Google** para seguir funcionando (mostrará "app sin verificar" solo si
   un tercero intentara autorizar — irrelevante aquí).
6. Correr una última vez la re-autorización para obtener un refresh token de larga vida:
   ```
   venv/bin/python3 scripts/reauth_gmail.py
   ```
7. Verificar: `curl -s localhost:8000/api/health/appliance` → `gmail.ok: true`.

## Red de seguridad ya instalada (si esto vuelve a fallar)

- `/api/health/appliance` valida el token en cada chequeo → `degraded` + instrucción de fix.
- Watchdog cada 15 min crea una **Alerta** en el NotificationCenter ante la transición.
- La revisión manual ya NO dice "Completado: no hay emails" cuando la API falla.
