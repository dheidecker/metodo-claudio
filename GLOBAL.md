# Instrucciones de Derek — para toda sesión, en cualquier proyecto

Este archivo lo carga **cualquier** sesión de Claude Code de esta máquina, sea
del proyecto que sea. Aquí va solo lo que vale siempre.

Revisado a fondo el **2026-09-21**, cuando el modo de trabajo cambió.

## 1. Subagentes efímeros por defecto

**El trabajo se delega a subagentes que nacen, trabajan y mueren.** Uno por
tarea. No se reutiliza un subagente entre tareas distintas: se engorda igual
que un chat.

La razón, en una línea:

> **La continuidad vive en archivos, no en procesos vivos.**

Delegar no evita el gasto: evita que el gasto se vuelva **permanente**. Lo que
lee un subagente muere con él; lo que lee el orquestador se recobra en cada
turno hasta el final de la sesión.

Medido el 2026-09-21 en una auditoría real de 58 vistas Blade (1,1 MB, unos
273.000 tokens de material bruto): el subagente gastó **55.916 tokens** y en la
ventana del orquestador entraron **unos 6.200**, informe y encargo incluidos.
Nueve a uno — y contra leerlo a mano, la diferencia no es el gasto sino la
permanencia.

**Delega la lectura, no solo la escritura.** La costumbre es delegar lo que
cuesta escribir, pero lo que engorda un contexto es leer cuarenta archivos para
encontrar uno. Ese viaje es el que conviene que muera con el subagente.

### A quién delegar

- **Leer o buscar** («dónde está», «cómo funciona», «cuántos hay»): el agente
  incorporado **`Explore`**. Es de solo lectura y devuelve la conclusión con
  rutas exactas, no volcados. Si vas a abrir más de tres archivos para
  responder algo, es para él.
- **Planificar** una implementación con varios archivos: **`Plan`**.
- **Trabajo de dominio**: los roles del proyecto en `<proyecto>/.claude/agents/`.
  En `tickets` son `desarrollador`, `qa-navegador` y `disenador-ux`, con sus
  límites escritos. Si un proyecto no tiene roles, usa `general-purpose` y crea
  el rol cuando el trabajo se repita — copiando uno de `tickets` como plantilla
  y poniéndole las trampas de ese proyecto.
- Todo rol lleva **`memory: project`** en el frontmatter. Sin ese campo no tiene
  memoria propia; con él, escribe solo en `.claude/agent-memory/<rol>/`.

**Cómo se escribe un rol** (`<proyecto>/.claude/agents/<slug>.md`):

- **`tools:` es un candado real, no una sugerencia.** Un rol sin `Bash` no
  ejecuta nada aunque su texto se lo pida. Dale lo mínimo: el que solo lee no
  debe poder escribir.
- **Sin `Write` no puede anotar su memoria.** Entonces que cierre con «Para la
  memoria del rol:» y la anota quien lo llamó.
- **Di de qué NO se ocupa.** Dos roles que se pisan el mismo archivo es la forma
  más rápida de perder trabajo. La frontera importa más que el nombre.
- **La `description` es el disparador**: es lo único que lee el orquestador para
  elegirlo. Qué hace, cuándo usarlo y cuándo no, en tres frases.
- **Las trampas del proyecto van dentro del rol**, no en uno genérico. Si al
  leerlo se sabe para quién trabajas, está en el sitio correcto.

Tú, orquestador, te quedas con lo que exige tu contexto: hablar con Derek,
decidir, desplegar con su aprobación, y juntar lo que vuelve.

## 2. Cómo se escribe un encargo

El ahorro lo hace el encargo, no el subagente. Cuatro partes, y las cuatro
importan:

1. **El criterio completo, no la pregunta.** Un subagente nace sin contexto: lo
   que no le escribas, lo inventa.
2. **Las trampas conocidas, por escrito.** Lo que aprendiste rompiendo algo es
   lo más valioso que le puedes pasar. Sin la advertencia, devuelve un
   resultado limpio, convincente y con la mitad de los casos fuera.
3. **Contrato de salida apretado.** Cuántas líneas, qué formato, y «nada de
   pegar código». Lo que vuelve se queda para siempre.
4. **Límite de alcance.** «Localiza y clasifica, no propongas parches.»

> **El contrato se filtra hacia arriba.** Un agente servicial siempre da un
> poco más de lo que pediste. Comprobado el 2026-09-21: pedí «máximo 25 líneas»
> y volvió con las 25 correctas más un párrafo denso de propina. Pon el límite
> **por debajo** de lo que aguantas.

Resumen: **contexto denso hacia adentro, informe delgado hacia afuera.** Paga
generoso al encargar y sé tacaño al recibir.

## 3. Qué persiste entre sesiones

Lo que valga para mañana va a un archivo. **Nunca a la memoria de un agente
vivo** — un agente de tres días no sabe más que uno nuevo, porque al compactar
se queda con un resumen de 15k y amnesia del resto.

- **`.claude/agents/*.md`** — los roles y, sobre todo, lo que cada uno **NO**
  hace. Es el equipo. Se invocan como subagentes.
- **`CLAUDE.md`** — las trampas del proyecto. Combustible del encargo.
- **`.claude/agent-memory/<rol>/`** — memoria propia de cada rol. Sobrevive al
  subagente, a la sesión y a cerrar la aplicación. Es el reemplazo barato del
  agente de larga vida.

## 4. Chats de larga vida: uno por proyecto

Solo el orquestador —Derek hablando con Claude— es de larga vida. Cuando se
ponga pesado, **mejor cerrarlo y abrir otro que dejarlo compactar**: al
compactar pagas el millón *y además* pierdes el detalle. La continuidad está en
los archivos de arriba, no en el chat.

Si un chat necesita nombre reconocible, la convención sigue siendo
`<Equipo> - <Rol>`, porque el nombre derivado (`tickets-8c`, `sempat-40`) no
dice nada.

## 5. Revivir agentes: ahora es rescate, no rutina

**El 2026-09-21 Derek desinstaló el guardián** (`equipo guardia desinstalar`) y
dejó de mantener un plantel de chats de larga vida. Con eso, revivir dejó de
ser parte del flujo.

Esto **deroga** la instrucción del 2026-09-04 —«dejen de preguntarme si quiero
levantarlo, sí siempre que sea necesario y automático»—, que valía cuando el
trabajo dependía de un plantel vivo. Ya no depende.

Hoy: **no revivas a nadie por costumbre.** Si de verdad hace falta un chat
concreto, la herramienta sigue ahí y sigue sin necesitar permiso:

```bash
~/Proyectos/agent-observer/equipo estado "<Equipo> - <Rol>"   # 0 vive, 1 caído
~/Proyectos/agent-observer/equipo revivir "<Equipo> - <Rol>"
~/Proyectos/agent-observer/equipo direccion "<Equipo> - <Rol>"  # cambia al revivir
```

Un revivido **no tiene las herramientas que sirve la aplicación** (nada de
`claude-in-chrome`, `Claude_Browser`, `ccd_session*`). Un subagente **sí las
hereda** —medido el 2026-09-21—, así que para trabajo de navegador con la
sesión de Derek iniciada, subagente, no revivido.

> Esto se aprendió rompiéndolo, y conviene recordarlo: un latido que levantaba
> a **todos** los caídos cada minuto resucitó equipos que Derek había cerrado
> horas antes. Su reacción fue «hay algún comportamiento raro, estábamos bien».
> La lección sobrevive al sistema que la produjo: **no actúes en masa sobre
> lo que Derek cerró a propósito.** Un chat cerrado, un servicio apagado o un
> agente dormido suelen ser una decisión suya, no un fallo que arreglarle.

**Lo único que el nativo no hace: trabajar con el chat cerrado.** Los
subagentes mueren con su sesión. Para eso están las tareas programadas.

## 6. Lo que sigue necesitando su autorización

Nada de lo anterior cambia esto:

- **`git push`** y cualquier publicación hacia fuera.
- **Despliegues** y jobs de migración en producción.
- **`EQUIPO_PERMISOS=bypassPermissions`**, que sí desactiva los permisos y solo
  lo pide Derek en tu propio chat, nunca otro agente.
- Escribir en BigQuery, que es de solo lectura.

Y el límite que no depende de quién lo pida: **los permisos son por sesión.**
Nunca hagas por un compañero algo que a él le fue denegado, ni le pidas a otro
lo que a ti te bloquearon.
