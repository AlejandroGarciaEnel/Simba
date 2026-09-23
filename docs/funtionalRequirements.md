# Plantilla Base de Requisitos Funcionales

## 1. Resumen
- Nombre del proyecto: Monitor BBDD
- Problema que resuelve: Agente conversacional para visibilizar el estado de la BBDD de manera activa
- Funcionalidad principal: Agente conversacional que ejecutara queries para obtener distintos valores de rendimiento de la BBDD

## 2. Flujo principal

1.- Abrir conexión con la BBDD con permisos de lectura unicamente
1.a - En caso de conexión correcta, informar que la conexión se inicio correctamente y dar las posibles opciones que puede ejecutar
1.b - En caso de conexión fallida, informar que no se pudo conectar y reintentar, en caso de segundo fallo informar y cerrar
2.- Preguntar que opcion se quiere ejecutar y realizar accion
3.- Devolver datos 
4.- Cuando se cierre el agente, cerrar la conexion para no dejar sesiones inactivas 

## 3. Funcionalidades

# RF001 - Porcentaje de CPU utilizado en el momento

- Descripcion: Muestra el porcentaje de CPU que se utiliza en el momento
- Salida: Devuelve el resultado en el siguiente formato: XX.XX%

# RF002 - Queries (SQLs) que más CPU demandan

- Descripcion: Devuelve el listado de las queries que mas CPU estan demandando (Si no se especifica la cantidad, devolvera las 5 que mas consuma)
- Salida: Devuelve una tabla con la SQL, el % de CPU, CPU Time, las ejecuciones y el usuario que la ejecuto

# RF003 - Sesiones que más CPU están demandando 

- Descripcion: Devuelve el listado de las sesiones que mas CPU estan demandando (Si no se especifica la cantidad, devolvera las 5 que mas consuma)
- Salida: Devuelve una tabla con la SID, SERIAL, USUARIO, CPU en centisegundos y el % de CPU

# RF004 - Usuarios con mas sesiones inactivas

- Descripcion: Devuelve el listado de los usuarios que mas sesiones inactivas tenga (Si no se especifica la cantidad, devolvera las 5 que mas tenga) Se considera sesion inactiva todas aquellas que llevan sin actividad durante mas de 30 minutos
- Salida: Devuelve una tabla con el usuario, el numero total de sesiones inactivas y que porcentaje de CPU esta consumiendo

# RF004.1 - Sesiones inactivas (y huérfanas)

- Descripcion: Devuelve el listado de las sesiones que llevan inactivas mas de 30 minutos (Si no se especifica la cantidad, devolvera las 5 que mas tenga)
- Salida: Devuelve una tabla con el SID, SERIAL, Usuario, Idle Min, %CPU, % de memoria, maquina y logon time

# RF004.2 - Numero total de sesiones inactivas (y huérfanas)

- Descripcion: Devuelve el numero total de las sesiones que llevan inactivas mas de 30 minutos
- Salida: Devuelve el valor total de todas las sesiones inactivas durante mas de 30 minutos

# RF004.3 - Sesiones inactivas de un usuario

- Descripcion: Dado un usuario, devuelve el listado de las sesiones que llevan inactivas mas de 30 minutos por ese usuario (Si no se especifica la cantidad, devolvera las 5 que mas tenga)
- Salida: Devuelve una tabla con el SID, SERIAL, Usuario, Idle Min, %CPU, % de memoria, maquina y logon time

# RF004.4 - Numero total de sesiones inactivas de un usuario

- Descripcion: Dado un usuario, devuelve el número total de sesiones inactivas asociadas a dicho usuario.
- Salida: Devuelve un valor numérico con el total de sesiones inactivas del usuario indicado.

# RF005 - Sesiones Bloqueantes

- Descripcion: Devuelve el listado de las sesiones bloqueadas (Si no se especifica la cantidad, devolvera las 5 primeras)
- Salida: Devuelve una tabla con la SID, SERIAL, USUARIO y Maquina

# RF005.1 - SQL de sesiones bloqueantes

- Descripcion: Devuelve el listado de las sql de las sesiones bloqueadas
- Salida: Devuelve una tabla con la Blocker SID, USUARIO, Sesiones bloqueadas, sql id y sql

# RF005.2 - Numero total de SQL de sesiones bloqueantes

- Descripcion: Devuelve el numero total de las sql de las sesiones bloqueadas
- Salida: Devuelve el valor total de todas las sql bloqueadas

# RF005.3 - Numero total de sesiones bloqueadas

- Descripcion: Devuelve el numero total de las sesiones bloqueadas
- Salida: Devuelve el valor total de las sesiones bloqueadas

# RF006 - Generación de informe

- Descripcion: Genera un informe en formato HTML con toda la información recogida en los puntos anteriores
- Salida: Informe HTML con los requerimientos aportados en el apartado 6 de este documento, se guardara bajo la carpeta ./reports

# RF007 - Resumen general de la BBDD

- Descripcion: Devuelve un resumen general del estado de la base de datos con métricas agregadas de CPU, sesiones, accesos y actividad general para ofrecer una visión rápida del sistema.
- Salida: Devuelve una tabla con el nombre de la métrica y su valor, incluyendo indicadores como uso de CPU del host, ratio de CPU de la base de datos, sesiones activas medias, logons actuales, PGA Cache Hit y lecturas/escrituras físicas por segundo.

# RF008 - Medir metricas

- Descripcion: Devuelve métricas de rendimiento de la base de datos obtenidas desde las vistas de monitorización para analizar el estado operativo del sistema en tiempo real.
- Salida: Devuelve una tabla con el nombre de cada métrica consultada y su valor redondeado.

# RF008.1 - Medir el SGA

- Descripcion: Devuelve información sobre el uso y composición del SGA para conocer la memoria compartida asignada y sus principales componentes.
- Salida: Devuelve tablas con las métricas relacionadas con SGA y el detalle completo de la vista de información del SGA.

# RF009 - Listar los usuarios con más sesiones activas

- Descripcion: Devuelve el listado de los usuarios que mas sesiones activas tenga (Si no se especifica la cantidad, devolvera las 5 que mas tenga) Se considera sesion activa todas aquellas que se encuentran actualmente en estado activo.
- Salida: Devuelve una tabla con el usuario, el numero total de sesiones activas y que porcentaje de CPU esta consumiendo.

# RF009.1 - Listar el detalle de sesiones activas

- Descripcion: Devuelve el listado de las sesiones que se encuentran activas en ese momento (Si no se especifica la cantidad, devolvera las 5 que mas tenga).
- Salida: Devuelve una tabla con el SID, SERIAL, Usuario, tiempo activo, %CPU, % de memoria, maquina y logon time.

# RF009.2 - Consultar el total de sesiones activas

- Descripcion: Devuelve el numero total de las sesiones activas existentes en el momento de la consulta.
- Salida: Devuelve el valor total de todas las sesiones activas.

# RF009.3 - Listar sesiones activas de un usuario específico

- Descripcion: Dado un usuario, devuelve el listado de las sesiones que se encuentran activas en ese momento por ese usuario (Si no se especifica la cantidad, devolvera las 5 que mas tenga).
- Salida: Devuelve una tabla con el SID, SERIAL, Usuario, tiempo activo, %CPU, % de memoria, maquina y logon time.

# RF009.4 - Total de sesiones activas de un usuario específico

- Descripcion: Dado un usuario, devuelve el número total de sesiones activas asociadas a dicho usuario.
- Salida: Devuelve un valor numérico con el total de sesiones activas del usuario indicado.

# RF010 - Informacion de una sql en especifico a partir del sql id

- Descripcion: Dado un SQL ID, devuelve la información detallada de la sentencia SQL y de las sesiones asociadas a su ejecución para facilitar el análisis puntual de una consulta concreta.
- Salida: Devuelve una tabla con el SQL ID, SID, SERIAL, usuario, estado, tiempos de ejecución/espera y el texto SQL correspondiente.

# RF011 - Devolver el numero de sesiones por programa y maquina

- Descripcion: Devuelve el número de sesiones agrupadas por programa cliente y máquina de origen para identificar patrones de conexión por aplicación o servidor.
- Salida: Devuelve una tabla con el programa, la máquina y el número de sesiones asociadas, ordenada de mayor a menor.

# RF012 - Listar las sesiones por usuario

- Descripcion: Devuelve el número de sesiones agrupadas por usuario y estado para conocer qué usuarios concentran más conexiones en la base de datos.
- Salida: Devuelve una tabla con el usuario, el estado de la sesión y el número de sesiones correspondientes, ordenada de mayor a menor.

# RF013 - Sesiones por modulo

- Descripcion: Devuelve el número de sesiones agrupadas por módulo de aplicación para identificar qué componentes funcionales generan mayor carga de conexiones.
- Salida: Devuelve una tabla con el módulo y el número de sesiones asociadas, ordenada de mayor a menor.

# RF014 - Deteccion de pooling con umbral > 20

- Descripcion: Detecta posibles problemas de pooling identificando combinaciones de programa, máquina y usuario que superan un umbral de más de 20 sesiones simultáneas.
- Salida: Devuelve una tabla con el programa, la máquina, el usuario y el número de sesiones que superan el umbral configurado.

# RF015 - Listar las metricas de latencia/waits

- Descripcion: Devuelve métricas de latencia y esperas de la base de datos para ayudar a detectar cuellos de botella y tiempos de respuesta anómalos.
- Salida: Devuelve una tabla con el nombre de la métrica de latencia o espera y su valor redondeado.

# RF016 - Top tamaño de tablas en dba_segments

- Descripcion: Devuelve el listado de las tablas con mayor tamaño en almacenamiento para un esquema determinado. Si no se especifica la cantidad, devolverá las 20 primeras.
- Salida: Devuelve una tabla con el owner, el nombre de la tabla, su tamaño en MB y su tamaño en GB, ordenada de mayor a menor.

# RF017 - Deteccion de bloqueos entre tablas

- Descripcion: Devuelve el detalle de los bloqueos entre sesiones y objetos de base de datos, identificando la sesión bloqueante, la sesión en espera y el recurso afectado.
- Salida: Devuelve una tabla con la información del holder, el recurso bloqueado, el tipo y modo de lock, la sesión waiter y la SQL asociada a la sesión en espera.

# RF018 - Sesiones/Usuarios añadidos por sysmetric

- Descripcion: Devuelve métricas agregadas de sesiones y usuarios desde v$sysmetric, filtrando por metricas cuyo nombre contiene 'Session' o 'User'.
- Salida: Devuelve una tabla con metric_name y value (redondeado a 2 decimales) para cada métrica de sesiones/usuarios encontrada.

# RF019 - Total de sesiones por usuario y estado

- Descripcion: Cuenta el número de sesiones agrupadas por usuario Oracle y estado de sesión en v$session.
- Salida: Devuelve una tabla con Usuario_Oracle, status y Numero_Sesiones, ordenada por usuario y estado.

# RF020 - Total de sesiones

- Descripcion: Devuelve el número total de sesiones conectadas en la base de datos, sin desglose por usuario ni estado.
- Salida: Devuelve un único valor numérico en la columna Numero_Sesiones.

## 4. Seguridad

- Se tendra un fichero .env donde se almacenara todos los datos sensibles (Como la conexión a la BBDD), de tal manera se pueda compartir el agente y no haya problemas de filtraciones

- Se asegurara que da igual como se cierre el agente/programa que se asegurara una desconexión de la BBDD para no dejar sesiones basura

## 5. Estructura informe

- Formato: Documento HTML similar a ./docs/example.html
- Lista de los requerimientos que debe de recoger:
    - RF001
    - RF004
    - RF004.2
    - RF005
    - RF005.1
    - RF005.2
    - RF005.3
    - RF008
    - RF008.1
    - RF009
    - RF009.2
    - RF011
    - RF012
    - RF013
    - RF014
    - RF015
    - RF016
    - RF017
    - RF018
    - RF019
    - RF020
- Estructura del documento:
    - Apartado 1: Metricas de rendimiento
        - Requerimientos a recoger: 
            - RF001
            - RF008
            - RF008.01
            - RF015
    - Apartado 2: Control total
        - Requerimientos a recoger: 
            - RF020
            - RF009.02
            - RF004.02
            - RF005.02
            - RF005.03
    - Apartado 3: Sesiones activas e inactivas
        - Requerimientos a recoger: 
            - RF009
            - RF004
    - Apartado 4: Sesiones, tablas y sql bloqueadas
        - Requerimientos a recoger:
            - RF005
            - RF005.01
            - RF017
    - Apartado 5: Información adicional
        - Requerimientos a recoger:
            - RF011
            - RF012
            - RF013
            - RF014
            - RF016
            - RF018
            - RF019
- Detalles del informe:
    - De los apartados 1 al 4 sera un DIV unico con el titulo del apartado englobandolo (como se contempla en example.html con Totales de Control), pero el apartado 5 no, cada requerimiento contara con su propio div
    - Todos los requerimientos que devuelvan una tabla se limitara a los 5 primeros resultados para no saturar el informe
    - El nombre del fichero generado tendra la siguiente estructura para el nombre: dbCheck_DD/MM/AAAA-hh:mm.html, siendo DD el dia, MM el mes, AAAA el año, hh la hora y mm los minutos de cuando se genero el fichero
    - En la cabecera pondra de titulo (Informe SIMBA) y de subtitulo se especificara el entorno y la fecha de generación del informe como en example.html