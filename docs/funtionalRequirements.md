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
- Salida: Informe HTML similar aportado al de la carpeta (../docs/example.html)
- Detalles: El requerimiento RF004.3 no es necesario incluirlo en el informe

## 4. Seguridad

- Se tendra un fichero .env donde se almacenara todos los datos sensibles (Como la conexión a la BBDD), de tal manera se pueda compartir el agente y no haya problemas de filtraciones

- Se asegurara que da igual como se cierre el agente/programa que se asegurara una desconexión de la BBDD para no dejar sesiones basura