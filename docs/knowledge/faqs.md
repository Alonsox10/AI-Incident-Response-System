# Preguntas frecuentes de soporte TI

Fuente de datos de la tabla `faqs`. Se parsea con `service/faq_loader.py` y se carga con `python seed.py`.

## Convención del archivo

El parser depende de esta estructura exacta. Si se rompe, la FAQ no se carga:

- `##` — categoría. Agrupa los casos que vienen debajo.
- `###` — la pregunta, redactada como la formularía el usuario. Es el texto que se vectoriza.
- `Severidad:` — una línea con la severidad del caso. Se guarda en `metadata`.
- `**Respuesta:**` — marcador que abre la respuesta. Todo lo que sigue, hasta el próximo encabezado, se guarda como `answer`.

Para agregar una FAQ nueva: copiar el bloque de cualquier caso, editarlo y volver a correr `python seed.py`.

---

## Red y conectividad

### ¿Qué hago si nos quedamos sin Internet en toda la oficina?

Severidad: Alta

**Respuesta:**

Normalmente es una caída del enlace WAN del proveedor de Internet (ISP) o un fallo en el router perimetral. La señal típica es que los equipos siguen obteniendo IP local pero no hay respuesta a ping externo.

Pasos a seguir:

1. Verificar los LEDs del router perimetral: el WAN debe estar activo.
2. Reiniciar el router/módem del ISP (apagar 30 segundos y encender).
3. Contactar al ISP con el número de ticket de soporte y reportar la incidencia.
4. Activar el enlace de respaldo (4G/LTE o segunda línea WAN) si existe.
5. Confirmar la restauración haciendo ping a 8.8.8.8 desde un equipo de prueba.

### ¿Por qué mi equipo tiene una IP 169.254.x.x y no navega?

Severidad: Media

**Respuesta:**

Esa dirección es una APIPA: significa que el equipo no recibió IP del servidor DHCP. Las causas habituales son un servidor DHCP caído, el rango de direcciones agotado o la interfaz de red deshabilitada.

Pasos a seguir:

1. Ejecutar `ipconfig /release` y luego `ipconfig /renew` en el equipo afectado.
2. Revisar el servicio DHCP en el servidor (`services.msc` o en el controlador de dominio).
3. Verificar que no se haya agotado el pool de direcciones; ampliar el rango si es necesario.
4. Revisar la conectividad física: cable, puerto de switch activo y sin errores.
5. Comprobar que el agente DHCP relay esté configurado si hay VLANs separadas.

### ¿Qué reviso cuando la red interna está muy lenta?

Severidad: Media

**Respuesta:**

La lentitud dentro de la LAN suele venir de una tormenta de broadcast, un duplex mismatch, port flapping o saturación de ancho de banda.

Pasos a seguir:

1. Conectarse al switch gestionable y revisar los contadores de errores por puerto (`show interface errors`).
2. Identificar el puerto con mayor tasa de broadcast/multicast y aislarlo.
3. Verificar la configuración de velocidad/duplex: debe estar en auto-negociación o coincidir en ambos extremos.
4. Revisar el dashboard de monitoreo (PRTG, Zabbix) para identificar el host que genera más tráfico.
5. Aplicar QoS o rate-limiting al tráfico no crítico si el ancho de banda está saturado.

### ¿Cómo soluciono que la VPN corporativa no conecte?

Severidad: Media

**Respuesta:**

El cliente VPN suele fallar por credenciales expiradas, certificado revocado, firewall bloqueando los puertos VPN o el servidor VPN caído.

Pasos a seguir:

1. Verificar que el usuario tenga credenciales válidas y no bloqueadas en Active Directory.
2. Comprobar que el certificado del cliente VPN esté vigente.
3. Confirmar que los puertos UDP 500 y 4500 (IKEv2/IPSec) o TCP 443 (SSL-VPN) estén abiertos en el firewall del ISP del usuario.
4. Revisar el estado del concentrador VPN (pfSense, Cisco ASA, Fortinet) y reiniciar el servicio si es necesario.
5. Revisar los logs del servidor VPN para identificar el error específico de autenticación.

---

## Seguridad

### ¿Cuál es el procedimiento ante una infección por ransomware?

Severidad: Crítica

**Respuesta:**

Se detecta por archivos cifrados con extensiones desconocidas y una nota de rescate visible. El origen suele ser un archivo malicioso abierto por phishing, un RDP expuesto o un USB infectado. La prioridad es contener antes que recuperar.

Pasos a seguir:

1. AISLAR de inmediato los equipos afectados desconectando el cable de red y deshabilitando el Wi-Fi.
2. NO apagar los equipos: hay que preservar la evidencia en memoria volátil para el análisis forense.
3. Notificar al equipo de seguridad y activar el plan de respuesta a incidentes.
4. Identificar el alcance revisando otros equipos de la red en busca de extensiones cifradas.
5. Restaurar desde el último backup limpio verificado.
6. Aplicar los parches pendientes (especialmente MS17-010/EternalBlue) y cambiar todas las contraseñas.
7. Reportar el incidente a las autoridades si corresponde (CERT nacional).

### ¿Qué hago si sospecho que una cuenta de usuario está comprometida?

Severidad: Alta

**Respuesta:**

Las señales son inicios de sesión desde ubicaciones inusuales, horarios atípicos o acciones no autorizadas en nombre de un usuario legítimo. Suele deberse a phishing exitoso, reutilización de contraseñas filtradas o una sesión robada por malware.

Pasos a seguir:

1. Deshabilitar de inmediato la cuenta afectada en Active Directory (`dsmod user` o la consola ADUC).
2. Forzar el cierre de todas las sesiones activas (revocar tokens OAuth/SAML si aplica).
3. Restablecer la contraseña y habilitar MFA de forma obligatoria.
4. Revisar el log de actividad de la cuenta en el SIEM (Splunk, Microsoft Sentinel) para determinar el alcance.
5. Comunicar al usuario el incidente y las recomendaciones de seguridad.
6. Verificar si se crearon reglas de reenvío en el correo o cambios de configuración no autorizados.

### ¿Cómo se mitiga un ataque DDoS contra nuestros servicios?

Severidad: Alta

**Respuesta:**

Se manifiesta como alta latencia o caídas intermitentes en servicios web o de correo, con volúmenes anómalos de tráfico entrante en el firewall. Puede ser un ataque volumétrico (Layer 3/4) o de aplicación (Layer 7).

Pasos a seguir:

1. Activar el modo de mitigación DDoS en el firewall/WAF (rate limiting, geo-blocking).
2. Contactar al ISP para aplicar scrubbing de tráfico o null-routing de la IP atacada.
3. Si se usa un CDN (Cloudflare, Akamai), activar el modo Under Attack.
4. Aumentar temporalmente la capacidad de los recursos o activar el autoescalado en cloud.
5. Analizar los patrones de ataque y crear reglas ACL para bloquear los rangos IP maliciosos.
6. Documentar el incidente para el análisis post-mortem y ajustar los umbrales de alerta.

### ¿Qué pasos sigo ante una fuga de datos confidenciales?

Severidad: Crítica

**Respuesta:**

Se trata de una transferencia no autorizada de datos sensibles hacia el exterior, por email, almacenamiento en la nube o dispositivos extraíbles. El origen puede ser un insider, malware exfiltrando datos o permisos mal configurados.

Pasos a seguir:

1. Identificar el vector de exfiltración mediante los logs del DLP (Data Loss Prevention).
2. Bloquear de inmediato el canal detectado (revocar acceso al servicio cloud, deshabilitar USB, etc.).
3. Preservar evidencias: logs, capturas de tráfico e imágenes forenses de los equipos involucrados.
4. Notificar al área legal y de compliance; evaluar las obligaciones de notificación regulatoria (GDPR, LGPD).
5. Realizar una auditoría de permisos y de acceso a datos sensibles.
6. Revisar y fortalecer las políticas DLP y los controles de acceso.

---

## Servidores e infraestructura

### ¿Qué hago si un servidor no responde a ping ni a los servicios?

Severidad: Alta

**Respuesta:**

Un servidor crítico sin respuesta puede estar apagado, con pantalla azul (BSOD) o con fallo de hardware. Las causas típicas son fallo físico, un driver o actualización defectuosa, sobrecalentamiento o corte de energía.

Pasos a seguir:

1. Verificar el estado físico del servidor: encendido, LEDs de error, temperatura.
2. Intentar acceso por consola remota iLO/IPMI/iDRAC para ver el estado sin acceso físico.
3. Revisar el Event Viewer o los logs del sistema operativo para identificar el error previo al fallo.
4. Si hay BSOD, anotar el código de parada y analizar el volcado de memoria con WinDbg.
5. Reiniciar de forma controlada desde la consola de administración remota.
6. Si el problema persiste, evaluar el failover a un servidor redundante o a la VM de respaldo.

### ¿Cómo libero espacio cuando un servidor tiene el disco al 100%?

Severidad: Alta

**Respuesta:**

El disco lleno impide escribir logs, bases de datos y archivos temporales, y los servicios empiezan a fallar. Casi siempre es acumulación de logs, temporales, backups locales o crecimiento no controlado de la base de datos.

Pasos a seguir:

1. Identificar los directorios que más consumen: `du -sh /*` en Linux o WinDirStat en Windows.
2. Limpiar archivos temporales: `/tmp`, `C:\Windows\Temp` y logs rotativos antiguos.
3. Archivar o mover los logs viejos a almacenamiento secundario (NAS, S3, Azure Blob).
4. Verificar si hay backups locales no eliminados y moverlos al destino correcto.
5. Configurar alertas de monitoreo al 75% y 85% de uso para prevenirlo a futuro.
6. Ampliar el volumen si es posible (LVM extend en Linux, extend volume en Windows).

### ¿Qué reviso si un servidor tiene la CPU por encima del 95%?

Severidad: Media

**Respuesta:**

La carga sostenida de CPU genera lentitud en todos los servicios que aloja. Puede ser un proceso descontrolado, un pico de carga legítimo, malware de minería o una configuración incorrecta.

Pasos a seguir:

1. Identificar el proceso consumidor: `top`/`htop` en Linux o Administrador de tareas > CPU en Windows.
2. Revisar si el proceso es legítimo o inesperado (posible minero de criptomonedas).
3. Si es legítimo con pico de carga, verificar si hay jobs batch programados y reprogramarlos.
4. Aplicar `nice`/`renice` para reducir la prioridad de los procesos no críticos en Linux.
5. Si es malware, aislar el servidor, matar el proceso e iniciar el análisis forense.
6. Revisar el historial de métricas en el sistema de monitoreo para identificar el patrón de inicio.

### ¿Qué hago si los backups están fallando?

Severidad: Alta

**Respuesta:**

Los jobs reportan errores o directamente no se ejecutan, y no hay confirmación de backup exitoso en los últimos días. Suele ser espacio insuficiente en el destino, credenciales expiradas, el agente caído o un cambio en la ruta de origen.

Pasos a seguir:

1. Revisar los logs del software de backup (Veeam, Acronis, Bacula) para identificar el error específico.
2. Verificar el espacio disponible en el destino del backup.
3. Comprobar que el servicio del agente de backup esté en ejecución en los servidores origen.
4. Validar que las credenciales de acceso al repositorio no hayan expirado.
5. Ejecutar un job de backup manual para confirmar la corrección del problema.
6. Revisar y actualizar el plan de DR (Disaster Recovery) si los backups llevan más de 24 horas sin completarse.

---

## Active Directory y usuarios

### ¿Cómo desbloqueo una cuenta de usuario en Active Directory?

Severidad: Baja

**Respuesta:**

El usuario ve el mensaje "Su cuenta ha sido bloqueada" al iniciar sesión. Se produce al superar el umbral de intentos fallidos, normalmente por contraseña incorrecta o una sesión guardada obsoleta en algún dispositivo.

Pasos a seguir:

1. Desbloquear la cuenta desde ADUC (Active Directory Users and Computers) o con `Unlock-ADAccount -Identity usuario`.
2. Identificar la fuente de los intentos fallidos con el Event ID 4740 en el Security Event Log del controlador de dominio.
3. Revisar si hay dispositivos móviles, servicios o tareas programadas con credenciales antiguas.
4. Asistir al usuario a actualizar la contraseña y verificar todos los dispositivos sincronizados.
5. Si el bloqueo es recurrente, revisar la Account Lockout Policy y considerar ajustar el umbral.

### ¿Qué hago si la replicación de Active Directory está fallando?

Severidad: Alta

**Respuesta:**

Los cambios hechos en un controlador de dominio no se propagan a los demás DCs, lo que genera inconsistencias en las autenticaciones. Puede ser un problema de conectividad entre DCs, el servicio de replicación detenido, un error de USN o un conflicto de objetos.

Pasos a seguir:

1. Ejecutar `repadmin /showrepl` para ver el estado de replicación entre todos los DCs.
2. Ejecutar `repadmin /replsummary` para identificar los errores específicos.
3. Verificar la conectividad RPC entre DCs: los puertos 135 y 49152-65535 deben estar abiertos.
4. Si hay error de USN rollback, retirar el DC afectado y promover uno nuevo.
5. Forzar la replicación con `repadmin /syncall /AdeP`.
6. Revisar Event Viewer > Directory Service en los DCs afectados.

### ¿Por qué una GPO no se aplica a los equipos del dominio?

Severidad: Media

**Respuesta:**

Las políticas de grupo configuradas no llegan a los equipos o usuarios objetivo. Suele deberse a filtros de seguridad incorrectos, un WMI filter mal configurado, problemas de conectividad con SYSVOL o herencia bloqueada.

Pasos a seguir:

1. Ejecutar `gpresult /H report.html` en el equipo afectado para ver las GPOs aplicadas y rechazadas.
2. Verificar los filtros de seguridad de la GPO: el equipo o usuario debe tener permisos de "Leer" y "Aplicar".
3. Comprobar el acceso a SYSVOL con `net use \\dominio\SYSVOL` desde el equipo afectado.
4. Verificar si hay bloqueo de herencia en la OU donde reside el objeto.
5. Forzar la actualización con `gpupdate /force` y reiniciar el equipo.
6. Revisar los Event ID 1058 y 1030 en el Application Event Log.

---

## Aplicaciones y software

### ¿Qué reviso cuando la aplicación web devuelve error 500?

Severidad: Alta

**Respuesta:**

El HTTP 500 indica una excepción no controlada en el backend. Las causas más comunes son la base de datos inaccesible, una configuración incorrecta tras un deployment o el disco lleno.

Pasos a seguir:

1. Revisar los logs de la aplicación (IIS, Apache, Nginx, Tomcat) para identificar el stack trace.
2. Verificar que el servidor de base de datos esté activo y acepte conexiones desde la app.
3. Comprobar que el último deployment no haya introducido errores, revisando el log de CI/CD.
4. Verificar el espacio en disco del servidor de aplicaciones.
5. Si está disponible, hacer rollback al deployment anterior que funcionaba.
6. Incrementar temporalmente el nivel de logging para capturar más detalle del error.

### ¿Cómo diagnostico una base de datos lenta o con timeouts?

Severidad: Alta

**Respuesta:**

Las consultas tardan mucho más de lo normal o generan timeouts, afectando a todas las aplicaciones dependientes. Las causas frecuentes son consultas sin índice, bloqueos (deadlocks), falta de recursos o estadísticas desactualizadas.

Pasos a seguir:

1. Identificar las consultas lentas con el slow query log (MySQL) o las DMVs de SQL Server (`sys.dm_exec_query_stats`).
2. Revisar si hay bloqueos activos: `SHOW PROCESSLIST` en MySQL o `sp_who2` en SQL Server.
3. Matar las sesiones bloqueadas si es necesario con `KILL [session_id]`.
4. Revisar el uso de recursos del servidor de BD: CPU, RAM e I/O de disco.
5. Actualizar estadísticas y reorganizar o reconstruir los índices fragmentados.
6. Revisar el plan de ejecución de las consultas más costosas y optimizarlas.

### ¿Qué hago si los usuarios no reciben correos?

Severidad: Alta

**Respuesta:**

Los mensajes quedan en cola o rebotan con NDR. Puede ser la cola saturada, el servicio SMTP detenido, la IP en blacklist, el certificado TLS vencido o un filtro antispam demasiado agresivo.

Pasos a seguir:

1. Revisar el estado del servidor de correo (Exchange, Postfix, SendGrid) y verificar que los servicios estén activos.
2. Revisar la cola de mensajes pendientes y los NDRs para identificar el código de error SMTP.
3. Verificar si la IP del servidor de correo está en blacklists (MXToolbox Blacklist Check).
4. Comprobar la validez del certificado TLS/SSL del servidor SMTP.
5. Revisar las reglas del filtro antispam que puedan estar bloqueando correos legítimos.
6. Si la IP está en blacklist, solicitar el deslistado y revisar la causa (posible relay abierto o cuenta comprometida enviando spam).

### ¿Qué hago si el SSO/SAML dejó de funcionar?

Severidad: Alta

**Respuesta:**

Los usuarios no pueden autenticarse en las aplicaciones con Single Sign-On: ven redireccionamiento infinito o error de aserción SAML. Las causas habituales son el certificado SAML vencido, desincronización de relojes (NTP), metadatos desactualizados o el IdP caído.

Pasos a seguir:

1. Verificar el estado del Identity Provider (Okta, Azure AD, ADFS, Keycloak).
2. Comprobar si el certificado de firma SAML del IdP o del SP ha vencido y renovarlo.
3. Verificar la sincronización NTP entre el IdP y los Service Providers (diferencia máxima: 2 minutos).
4. Actualizar los metadatos SAML en el SP si el IdP cambió certificados o endpoints.
5. Revisar los logs de SAML en el IdP y en el SP para identificar el error de aserción específico.
6. Como contingencia, habilitar el acceso directo con usuario y contraseña mientras se resuelve el SSO.

---

## Equipos de usuario final

### ¿Por qué mi equipo tarda tanto en iniciar?

Severidad: Baja

**Respuesta:**

Un arranque de más de 10 minutos con alta carga de disco o CPU suele deberse a demasiados programas en inicio automático, un disco HDD con sectores defectuosos, falta de RAM o malware.

Pasos a seguir:

1. Revisar y deshabilitar los programas de inicio innecesarios: `msconfig` > Inicio, o Administrador de tareas > Inicio.
2. Verificar la salud del disco con `chkdsk /f /r` o revisando S.M.A.R.T. con CrystalDiskInfo.
3. Ejecutar un análisis antimalware completo con Windows Defender o Malwarebytes.
4. Verificar la RAM con Windows Memory Diagnostic para descartar fallas de memoria.
5. Si el disco es HDD y tiene muchos sectores defectuosos, planificar su reemplazo por SSD.
6. Limpiar archivos temporales con `cleanmgr` y vaciar la Papelera de reciclaje.

### ¿Qué significa que me salga pantalla azul (BSOD) repetidamente?

Severidad: Media

**Respuesta:**

Los BSOD recurrentes con distintos códigos (IRQL_NOT_LESS_OR_EQUAL, MEMORY_MANAGEMENT) apuntan a un driver incompatible o corrupto, un fallo de RAM, un error en las actualizaciones de Windows o un problema de hardware.

Pasos a seguir:

1. Anotar el código de parada y analizar el minidump de `C:\Windows\Minidump` con WinDbg.
2. Revisar los eventos del sistema en Event Viewer antes del BSOD para identificar el driver causante.
3. Desinstalar el último driver o actualización de Windows instalada antes de que comenzaran los BSOD.
4. Ejecutar `sfc /scannow` y `DISM /Online /Cleanup-Image /RestoreHealth` para reparar archivos del sistema.
5. Probar la RAM con MemTest86 durante al menos 2 pasadas completas.
6. Si el problema persiste, considerar la reinstalación limpia del sistema operativo.

### ¿Cómo arreglo una impresora que aparece sin conexión?

Severidad: Baja

**Respuesta:**

La impresora figura como "Sin conexión" o los trabajos quedan atascados en la cola. Suele ser el servicio Print Spooler detenido, un driver corrupto, un atasco en la cola o un problema de red.

Pasos a seguir:

1. Reiniciar el servicio Print Spooler: `services.msc` > Cola de impresión > Reiniciar.
2. Limpiar la cola de impresión: detener el servicio, borrar el contenido de `C:\Windows\system32\spool\PRINTERS` y reiniciar el servicio.
3. Verificar la conectividad con la impresora haciendo ping a su IP o comprobando que esté encendida.
4. Reinstalar el driver de impresora desde la web del fabricante.
5. Si es una impresora de red, verificar que el puerto TCP/IP configurado tenga su IP correcta.
6. Verificar en el servidor de impresión, si existe, que la impresora compartida esté activa.

---

## Cloud e infraestructura como código

### ¿Qué hago si una instancia cloud quedó inaccesible tras un mantenimiento?

Severidad: Alta

**Respuesta:**

Una instancia EC2, VM de Azure o VM de GCP puede quedar inaccesible tras una actualización del sistema operativo. Las causas típicas son el Security Group o NSG bloqueando SSH/RDP, el servicio SSH detenido, la IP pública liberada o el disco de arranque corrupto.

Pasos a seguir:

1. Verificar el Security Group (AWS), NSG (Azure) o Firewall Rules (GCP): los puertos 22 (SSH) o 3389 (RDP) deben permitir tu IP.
2. Verificar que la instancia tenga IP pública o Elastic IP asignada correctamente.
3. Acceder por la consola serial del proveedor cloud para diagnosticar sin SSH/RDP.
4. Revisar los system logs de la instancia desde la consola del proveedor.
5. Si el arranque está corrupto, desconectar el volumen y adjuntarlo a una instancia auxiliar para reparar el filesystem.
6. Revisar que el servicio `sshd` esté habilitado y en ejecución dentro de la instancia.

### ¿Qué reviso cuando el pipeline de CI/CD falla?

Severidad: Media

**Respuesta:**

El pipeline puede fallar en build, test o deploy, bloqueando la entrega a producción. Las causas más comunes son un error en el código, un test fallido, credenciales de deployment expiradas, un problema con el runner o dependencias rotas.

Pasos a seguir:

1. Revisar los logs del pipeline (GitHub Actions, GitLab CI, Jenkins) para identificar la etapa y el error exacto.
2. Si falla en Build, revisar los cambios recientes en el código o en las dependencias (`npm audit`, `pip check`).
3. Si falla en Test, revisar los tests fallidos y corregir el código o el entorno de pruebas.
4. Si falla en Deploy, verificar que los secretos y credenciales (tokens, SSH keys) estén vigentes.
5. Verificar que el runner tenga conectividad al entorno de destino.
6. Revisar si hay conflictos de versiones de herramientas en el entorno del runner.
