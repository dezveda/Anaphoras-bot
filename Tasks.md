# Tasks de Desarrollo: Bot de Trading Algorítmico

Este documento detalla las tareas individuales para cada fase del desarrollo del bot de trading, con una estratificación de 3 niveles de detalle.

---

## Fase 1: Investigación y Diseño Detallado

*   **1.1 Investigación API Binance Futuros**
    *   1.1.1 Estudiar la documentación oficial de Binance API para Futuros (REST y WebSocket).
        *   1.1.1.1 Identificar endpoints para datos de mercado (klines, profundidad, trades).
        *   1.1.1.2 Identificar endpoints para gestión de órdenes (crear, cancelar, consultar).
        *   1.1.1.3 Comprender los límites de velocidad (rate limits) y cómo manejarlos.
    *   1.1.2 Investigar sobre autenticación (API Key, Secret Key) y seguridad.
        *   1.1.2.1 Mejores prácticas para el manejo seguro de credenciales.
    *   1.1.3 Explorar la Testnet de Binance Futuros para pruebas iniciales.
        *   1.1.3.1 Proceso de obtención de claves API para la Testnet.

*   **1.2 Selección Final de Bibliotecas Python**
    *   1.2.1 Evaluar bibliotecas para la interfaz gráfica (GUI).
        *   1.2.1.1 Comparar Tkinter, PyQt, y Kivy en términos de facilidad de uso, características y dependencias para Windows 10.
        *   1.2.1.2 Tomar una decisión sobre la biblioteca GUI a utilizar.
    *   1.2.2 Evaluar bibliotecas para la conectividad con Binance.
        *   1.2.2.1 Analizar `python-binance` vs. uso directo de `requests` y `websockets`.
        *   1.2.2.2 Seleccionar el enfoque para la interacción con la API.
    *   1.2.3 Confirmar bibliotecas para análisis de datos (Pandas, NumPy).
        *   1.2.3.1 Investigar si se usará TA-Lib u otra para indicadores técnicos.
    *   1.2.4 Evaluar bibliotecas o enfoques para backtesting.
        *   1.2.4.1 Considerar `Backtesting.py`, `bt`, o desarrollo propio.
        *   1.2.4.2 Decidir la herramienta o método de backtesting.

*   **1.3 Diseño Detallado de Módulos del Bot**
    *   1.3.1 Diseñar la interfaz y funcionalidad del `BinanceConnector`.
        *   1.3.1.1 Definir métodos para llamadas REST y manejo de WebSockets.
        *   1.3.1.2 Especificar manejo de errores y reconexiones.
    *   1.3.2 Diseñar `DataFetcher`.
        *   1.3.2.1 Estructura de datos para almacenar información de mercado.
        *   1.3.2.2 Lógica de preprocesamiento de datos.
    *   1.3.3 Diseñar `StrategyEngine`.
        *   1.3.3.1 Cómo se cargarán y gestionarán múltiples estrategias.
        *   1.3.3.2 Interfaz común para todas las estrategias.
    *   1.3.4 Diseñar `OrderExecutor`.
        *   1.3.4.1 Flujo de creación y seguimiento de órdenes.
        *   1.3.4.2 Manejo de estados de órdenes (abierta, completada, cancelada, error).
    *   1.3.5 Diseñar `Backtester`.
        *   1.3.5.1 Formato de entrada de datos históricos.
        *   1.3.5.2 Métricas de rendimiento a calcular (Profit, Drawdown, Sharpe Ratio, etc.).
    *   1.3.6 Diseñar `RiskManager`.
        *   1.3.6.1 Lógica para cálculo de tamaño de posición.
        *   1.3.6.2 Definición de reglas de stop-loss y take-profit.
    *   1.3.7 Diseñar `Logger`.
        *   1.3.7.1 Formato de los logs.
        *   1.3.7.2 Niveles de logging (INFO, WARNING, ERROR).
    *   1.3.8 (Opcional) Diseñar `AICommunicator`.
        *   1.3.8.1 Especificar formato del archivo de intercambio (ej. JSON, CSV).
        *   1.3.8.2 Definir la frecuencia y triggers para lectura/escritura.

*   **1.4 Definición Detallada de Estrategias de Trading**
    *   1.4.1 Especificar parámetros y lógica para DCA Avanzado.
        *   1.4.1.1 Definir niveles de entrada, cantidad por nivel.
        *   1.4.1.2 Condiciones para iniciar y detener DCA.
    *   1.4.2 Especificar lógica para Hedging de Operación Inversa.
        *   1.4.2.1 Condiciones para abrir una posición de cobertura.
        *   1.4.2.2 Ratio de la cobertura.
    *   1.4.3 Detallar aplicación de Fibonacci Circular en Cascada.
        *   1.4.3.1 Cómo identificar puntos de anclaje para los círculos.
        *   1.4.3.2 Cómo interpretar los niveles de los círculos concéntricos para entradas/salidas.
    *   1.4.4 Definir el uso de Puntos Pivote.
        *   1.4.4.1 Cálculo de puntos pivote (diario, semanal).
        *   1.4.4.2 Heurísticas para operar en base a soportes y resistencias pivote.
    *   1.4.5 Detallar el análisis de Puntos de Liquidez.
        *   1.4.5.1 Identificación de zonas de alta liquidez (ej. order book imbalance, price clustering).
        *   1.4.5.2 Heurísticas para operar anticipando movimientos hacia/desde estos puntos.
    *   1.4.6 Especificar la adaptación mecanizada a cambios de tendencia.
        *   1.4.6.1 Indicadores para identificar cambios de tendencia (ej. Medias Móviles, MACD).
        *   1.4.6.2 Lógica para ajustar la dirección de las operaciones y el enfoque en macrotendencias.
    *   1.4.7 Definir el monitoreo de (sub)indicadores y su heurística.
        *   1.4.7.1 Selección de indicadores (RSI, Stoch, Volumen, etc.).
        *   1.4.7.2 Desarrollo de heurísticas combinadas para señales de trading.

*   **1.5 Esbozo Inicial de la Interfaz de Usuario (GUI)**
    *   1.5.1 Definir las vistas principales y la navegación.
        *   1.5.1.1 Mockups o wireframes básicos de cada pantalla.
    *   1.5.2 Listar los controles y visualizaciones necesarias.
        *   1.5.2.1 Gráficos, tablas, botones, campos de entrada.

---

## Fase 2: Desarrollo del Núcleo del Bot

*   **2.1 Desarrollo del `BinanceConnector`**
    *   2.1.1 Implementar autenticación segura con API de Binance.
        *   2.1.1.1 Función para firmar solicitudes (HMAC SHA256).
        *   2.1.1.2 Almacenamiento seguro o carga de API keys.
    *   2.1.2 Desarrollar funciones para endpoints REST de Futuros.
        *   2.1.2.1 Obtener información de la cuenta (balance, posiciones).
        *   2.1.2.2 Obtener datos históricos de klines.
        *   2.1.2.3 Enviar y cancelar órdenes.
        *   2.1.2.4 Consultar estado de órdenes.
    *   2.1.3 Implementar conexión WebSocket para datos en tiempo real.
        *   2.1.3.1 Suscripción a streams (klines, profundidad, trades específicos de BTC/USDT Futuros).
        *   2.1.3.2 Manejo de mensajes WebSocket y parseo de datos.
        *   2.1.3.3 Implementar lógica de reconexión automática en caso de fallo.
    *   2.1.4 Implementar manejo de errores y límites de la API.
        *   2.1.4.1 Retry logic con backoff exponencial para errores comunes.
        *   2.1.4.2 Respetar los rate limits.

*   **2.2 Desarrollo del `DataFetcher`**
    *   2.2.1 Integrar con `BinanceConnector` para recibir datos de WebSocket.
        *   2.2.1.1 Callback o sistema de colas para procesar datos entrantes.
    *   2.2.2 Implementar el almacenamiento y preprocesamiento de datos.
        *   2.2.2.1 Estructuras de datos (ej. Pandas DataFrames) para klines, libro de órdenes, etc.
        *   2.2.2.2 Cálculo de indicadores básicos si es necesario en esta etapa (ej. VWAP simple).
    *   2.2.3 Asegurar la sincronización y consistencia de los datos.
        *   2.2.3.1 Manejo de timestamps y posible desorden de mensajes.

*   **2.3 Desarrollo inicial del `OrderExecutor`**
    *   2.3.1 Implementar funciones para colocar órdenes de mercado y límite.
        *   2.3.1.1 Interacción con `BinanceConnector` para enviar la orden.
        *   2.3.1.2 Validación básica de parámetros de la orden.
    *   2.3.2 Implementar funciones para cancelar órdenes.
        *   2.3.2.1 Cancelar una orden específica por ID.
        *   2.3.2.2 (Opcional) Cancelar todas las órdenes abiertas.
    *   2.3.3 Implementar seguimiento básico del estado de las órdenes.
        *   2.3.3.1 Consultar el estado de una orden enviada.

*   **2.4 Implementación del `Logger` Básico**
    *   2.4.1 Configurar la biblioteca de logging de Python.
        *   2.4.1.1 Definir formato de mensaje (timestamp, nivel, módulo, mensaje).
        *   2.4.1.2 Configurar salida a archivo y/o consola.
    *   2.4.2 Integrar logging en los módulos desarrollados (`BinanceConnector`, `DataFetcher`).
        *   2.4.2.1 Registrar eventos importantes, errores, y decisiones.

---

## Fase 3: Implementación de Estrategias de Trading y Backtesting

*   **3.1 Desarrollo del `StrategyEngine`**
    *   3.1.1 Crear una clase base abstracta para las estrategias.
        *   3.1.1.1 Definir métodos comunes (ej. `on_data()`, `on_order_update()`).
    *   3.1.2 Implementar un gestor de estrategias que las cargue y ejecute.
        *   3.1.2.1 Permitir habilitar/deshabilitar estrategias dinámicamente (si es posible).
        *   3.1.2.2 Pasar datos de mercado a las estrategias activas.

*   **3.2 Implementación de Estrategias Individuales**
    *   3.2.1 Desarrollar estrategia de DCA Avanzado.
        *   3.2.1.1 Codificar la lógica de niveles de compra y toma de beneficios.
        *   3.2.1.2 Integrar con `OrderExecutor`.
    *   3.2.2 Desarrollar estrategia de Hedging.
        *   3.2.2.1 Lógica para abrir/cerrar posiciones de cobertura.
        *   3.2.2.2 Cálculo del tamaño de la cobertura.
    *   3.2.3 Desarrollar estrategia de Fibonacci Circular.
        *   3.2.3.1 Algoritmo para calcular y dibujar/interpretar los círculos.
        *   3.2.3.2 Generación de señales de trading basadas en los niveles.
    *   3.2.4 Desarrollar estrategia de Puntos Pivote.
        *   3.2.4.1 Función para calcular puntos pivote y niveles S/R.
        *   3.2.4.2 Lógica de trading en base a estos niveles.
    *   3.2.5 Desarrollar estrategia de Puntos de Liquidez.
        *   3.2.5.1 Algoritmos para identificar zonas de liquidez (ej. análisis del libro de órdenes).
        *   3.2.5.2 Heurísticas para operar en estas zonas.
    *   3.2.6 Desarrollar adaptación a cambios de tendencia.
        *   3.2.6.1 Implementar indicadores de tendencia.
        *   3.2.6.2 Lógica para ajustar parámetros o cambiar de estrategia secundaria.
    *   3.2.7 Desarrollar monitoreo de (sub)indicadores y heurísticas.
        *   3.2.7.1 Cálculo de los indicadores seleccionados (RSI, MACD, etc.).
        *   3.2.7.2 Codificación de las reglas heurísticas para generar señales.

*   **3.3 Desarrollo del `Backtester`**
    *   3.3.1 Implementar carga de datos históricos (CSV, API de Binance).
        *   3.3.1.1 Funciones para obtener y formatear datos históricos de BTC/USDT Futuros.
    *   3.3.2 Desarrollar el motor de simulación de trading.
        *   3.3.2.1 Iterar sobre datos históricos, alimentando a las estrategias.
        *   3.3.2.2 Simular ejecución de órdenes (considerando comisiones, slippage básico).
    *   3.3.3 Implementar cálculo de métricas de rendimiento.
        *   3.3.3.1 Total P/L, P/L porcentual, Winrate, Max Drawdown, Sharpe Ratio.
        *   3.3.3.2 Generación de reportes o visualizaciones de resultados.
    *   3.3.4 Integrar estrategias con el `Backtester`.
        *   3.3.4.1 Permitir seleccionar y configurar estrategias para backtesting.

*   **3.4 Integración Inicial de Estrategias con `OrderExecutor` y `RiskManager` Básico**
    *   3.4.1 Conectar señales de estrategias al `OrderExecutor`.
        *   3.4.1.1 Traducir señales de "comprar/vender" en órdenes concretas.
    *   3.4.2 Implementar lógica básica de `RiskManager` (ej. tamaño de posición fijo o % del capital).
        *   3.4.2.1 Aplicar el tamaño de posición a las órdenes generadas.

---

## Fase 4: Desarrollo de la Interfaz de Usuario (GUI)

*   **4.1 Configuración del Proyecto GUI**
    *   4.1.1 Instalar la biblioteca GUI seleccionada (Tkinter, PyQt, etc.).
    *   4.1.2 Estructurar los archivos y carpetas para el código de la GUI.

*   **4.2 Desarrollo del Dashboard Principal**
    *   4.2.1 Mostrar estado general del bot (conectado, operando, errores).
        *   4.2.1.1 Indicadores visuales de estado.
    *   4.2.2 Visualizar P&L actual y total.
        *   4.2.2.1 Actualización en tiempo real o periódica.
    *   4.2.3 Mostrar información clave de BTC/USDT (precio actual, cambio 24h).
        *   4.2.3.1 Integrar con `DataFetcher`.

*   **4.3 Desarrollo de la Sección de Configuración**
    *   4.3.1 Permitir la configuración de claves API de Binance (de forma segura).
        *   4.3.1.1 Campos de entrada y opción para guardar/cargar configuración.
    *   4.3.2 Configuración de parámetros generales del bot (ej. capital a usar, par a operar - aunque fijo a BTC/USDT).
    *   4.3.3 Configuración específica para cada estrategia de trading.
        *   4.3.3.1 Habilitar/deshabilitar estrategias.
        *   4.3.3.2 Ajustar parámetros (niveles DCA, sensibilidad de indicadores, etc.).

*   **4.4 Desarrollo de Visualizaciones de Mercado**
    *   4.4.1 Implementar un gráfico de precios en tiempo real (básico).
        *   4.4.1.1 Usar bibliotecas como Matplotlib (con backend GUI) o funcionalidades nativas de PyQtGraph.
        *   4.4.1.2 Mostrar velas (candlesticks) y volumen.
    *   4.4.2 (Opcional) Mostrar indicadores técnicos sobre el gráfico.
        *   4.4.2.1 Permitir al usuario seleccionar qué indicadores visualizar.

*   **4.5 Desarrollo del Monitor de Órdenes y Posiciones**
    *   4.5.1 Mostrar órdenes abiertas, historial de órdenes.
        *   4.5.1.1 Obtener datos de `OrderExecutor` o `BinanceConnector`.
    *   4.5.2 Mostrar posiciones actuales (tamaño, precio de entrada, P&L no realizado).
        *   4.5.2.1 Actualización en tiempo real.

*   **4.6 Desarrollo de la Interfaz de Backtesting**
    *   4.6.1 Permitir seleccionar el rango de fechas para datos históricos.
        *   4.6.1.1 Controles de calendario o entrada de fechas.
    *   4.6.2 Permitir seleccionar y configurar estrategias para el backtest.
        *   4.6.2.1 Similar a la configuración general de estrategias.
    *   4.6.3 Botón para iniciar el backtest y mostrar progreso.
    *   4.6.4 Visualizar resultados del backtest (métricas, gráfico de equidad).
        *   4.6.4.1 Tablas y gráficos para presentar los resultados.

*   **4.7 Integración de la GUI con los Módulos del Backend**
    *   4.7.1 Establecer comunicación entre la GUI y los módulos (`DataFetcher`, `StrategyEngine`, `OrderExecutor`, `Backtester`).
        *   4.7.1.1 Uso de hilos, colas o señales/slots (PyQt) para evitar que la GUI se congele.
    *   4.7.2 Asegurar que la GUI refleje el estado actual del bot y los datos.
        *   4.7.2.1 Actualizaciones fluidas de la información.

---

## Fase 5: Integración, Pruebas Exhaustivas y Refinamiento

*   **5.1 Integración Completa de Módulos**
    *   5.1.1 Asegurar que todos los módulos interactúan correctamente.
        *   5.1.1.1 Flujo de datos desde `DataFetcher` a `StrategyEngine`, a `OrderExecutor`, y reflejado en `GUI`.
    *   5.1.2 Verificar la correcta gestión de estados y errores a través del sistema.

*   **5.2 Implementación y Mejora del `RiskManager`**
    *   5.2.1 Implementar reglas de stop-loss dinámico.
        *   5.2.1.1 Basado en volatilidad (ATR), porcentaje, o niveles técnicos.
    *   5.2.2 Implementar reglas de take-profit.
        *   5.2.2.1 Múltiples niveles de take-profit si es necesario.
    *   5.2.3 Perfeccionar el cálculo del tamaño de la posición.
        *   5.2.3.1 Considerar el riesgo por operación y el balance de la cuenta.
    *   5.2.4 Integrar `RiskManager` con `StrategyEngine` y `OrderExecutor`.
        *   5.2.4.1 El `RiskManager` debe poder anular o modificar órdenes si se violan las reglas de riesgo.

*   **5.3 Pruebas Unitarias**
    *   5.3.1 Escribir pruebas para funciones críticas de cada módulo.
        *   5.3.1.1 Usar `unittest` o `pytest`.
        *   5.3.1.2 Mockear dependencias externas como la API de Binance.
    *   5.3.2 Asegurar una buena cobertura de código.

*   **5.4 Pruebas de Integración**
    *   5.4.1 Probar flujos completos del sistema.
        *   5.4.1.1 Desde la recepción de datos hasta la ejecución simulada de una orden.
        *   5.4.1.2 Probar la interacción entre la GUI y el backend.
    *   5.4.2 Verificar la consistencia de los datos entre módulos.

*   **5.5 Pruebas de Rendimiento y Estrés**
    *   5.5.1 Evaluar el rendimiento del bot bajo alta carga de datos de mercado.
        *   5.5.1.1 Medir latencia en el procesamiento de datos y toma de decisiones.
    *   5.5.2 Probar la estabilidad del bot durante largos periodos de ejecución.
        *   5.5.2.1 Monitorear uso de memoria y CPU.

*   **5.6 Paper Trading en Testnet de Binance**
    *   5.6.1 Configurar el bot para operar en la Testnet de Binance Futuros.
        *   5.6.1.1 Usar claves API de Testnet.
    *   5.6.2 Ejecutar el bot con dinero ficticio durante un periodo significativo.
        *   5.6.2.1 Monitorear su comportamiento y rendimiento en condiciones de mercado simuladas pero realistas.
    *   5.6.3 Registrar y analizar los resultados del paper trading.

*   **5.7 Corrección de Errores y Refinamiento**
    *   5.7.1 Solucionar bugs identificados durante las pruebas.
    *   5.7.2 Optimizar el código para mejorar rendimiento o claridad.
    *   5.7.3 Ajustar parámetros de estrategias basados en resultados de backtesting y paper trading.

---

## Fase 6: (Opcional) Implementación de Comunicación con IA de Windsurf

*   **6.1 Definición Final del Formato del Archivo de Comunicación**
    *   6.1.1 Confirmar la estructura (JSON, CSV, etc.) y los campos de datos.
        *   6.1.1.1 Especificar qué información escribirá el bot (ej. señales de trading, estado del mercado).
        *   6.1.1.2 Especificar qué información leerá el bot (ej. ajustes de parámetros, señales externas).
    *   6.1.2 Establecer la ubicación del archivo.

*   **6.2 Implementación de la Lógica de Lectura/Escritura**
    *   6.2.1 Desarrollar funciones en el `AICommunicator` para escribir datos al archivo.
        *   6.2.1.1 Asegurar escritura atómica o manejo de concurrencia si es necesario.
    *   6.2.2 Desarrollar funciones para leer datos del archivo.
        *   6.2.2.1 Decidir la frecuencia de lectura (ej. periódica, basada en modificación de archivo).
    *   6.2.3 Integrar la información leída en la lógica de toma de decisiones del bot (si aplica).
        *   6.2.3.1 Cómo las señales de la IA pueden influir o anular las decisiones del bot.

*   **6.3 Pruebas de la Comunicación Asincrónica**
    *   6.3.1 Simular la interacción de la IA de Windsurf modificando el archivo.
        *   6.3.1.1 Verificar que el bot lee y reacciona correctamente a los cambios.
    *   6.3.2 Verificar que el bot escribe correctamente la información para la IA.

---

## Fase 7: Documentación Final y Entrega

*   **7.1 Revisión y Finalización de `Plan.md` y `Tasks.md`**
    *   7.1.1 Asegurar que ambos documentos reflejen el estado final del proyecto.
        *   7.1.1.1 Actualizar con cualquier cambio o decisión tomada durante el desarrollo.
    *   7.1.2 Verificar la coherencia y completitud.

*   **7.2 Creación de Documentación Técnica**
    *   7.2.1 Describir la arquitectura final del sistema.
        *   7.2.1.1 Diagramas de componentes y sus interacciones.
    *   7.2.2 Documentar las APIs internas de cada módulo.
        *   7.2.2.1 Explicar las funciones principales, sus parámetros y lo que retornan.
    *   7.2.3 Guía de configuración y despliegue.
        *   7.2.3.1 Cómo instalar dependencias y ejecutar el bot.

*   **7.3 Creación de Manual de Usuario Básico**
    *   7.3.1 Explicar cómo usar la interfaz gráfica.
        *   7.3.1.1 Configuración inicial, inicio/parada del bot.
        *   7.3.1.2 Interpretación de la información mostrada.
        *   7.3.1.3 Cómo ejecutar y ver resultados de backtesting.
    *   7.3.2 Guía de solución de problemas comunes.

*   **7.4 Empaquetado del Bot para Windows 10 (Opcional)**
    *   7.4.1 Investigar herramientas como PyInstaller o cx_Freeze.
        *   7.4.1.1 Crear un ejecutable standalone para facilitar la distribución.
    *   7.4.2 Probar el ejecutable en un entorno limpio de Windows 10.

---
