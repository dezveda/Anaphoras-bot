# Plan de Desarrollo: Bot de Trading Algorítmico para Binance Futuros (BTC/USDT)

## 1. Introducción

Este documento describe el plan de desarrollo para un bot de trading algorítmico minimalista pero robusto, diseñado para operar en Windows 10 (64 bits). El bot se conectará a la API de Binance para monitorear información en vivo del par BTC/USDT y ejecutar operaciones en el mercado de Futuros BTC/USDT. El objetivo principal es obtener altos rendimientos mediante la aplicación de técnicas avanzadas de análisis de datos y financiero algorítmico, sin depender directamente de IA (TensorFlow) o Docker. Se considerará una vía de comunicación asincrónica con la IA de Windsurf.

## 2. Arquitectura General

El bot se desarrollará en Python y constará de los siguientes módulos principales:

*   **Módulo de Conexión API (BinanceConnector)**: Encargado de toda la comunicación con la API de Binance (REST y WebSockets) para Futuros. Gestionará la autenticación, el envío de órdenes, la obtención de datos de mercado y la información de la cuenta.
*   **Módulo de Adquisición de Datos (DataFetcher)**: Responsable de obtener y preprocesar datos de mercado en tiempo real (precios, volumen, libro de órdenes, etc.) para el par BTC/USDT.
*   **Módulo de Estrategias de Trading (StrategyEngine)**: Contendrá la lógica para las diversas estrategias de trading a implementar (DCA avanzado, hedging, Fibonacci circular, análisis de puntos pivote, análisis de liquidez, adaptación a tendencias).
*   **Módulo de Ejecución de Órdenes (OrderExecutor)**: Gestionará la colocación, modificación y cancelación de órdenes en Binance Futuros, incluyendo órdenes de mercado, límite, stop-loss y take-profit.
*   **Módulo de Backtesting (Backtester)**: Permitirá probar las estrategias de trading con datos históricos de Binance Futuros BTC/USDT para evaluar su rendimiento y optimizar parámetros.
*   **Módulo de Interfaz de Usuario (GUI)**: Proporcionará una interfaz gráfica para que el usuario monitoree el bot, configure parámetros, visualice datos y resultados de backtesting.
*   **Módulo de Gestión de Riesgos (RiskManager)**: Implementará lógicas para controlar el riesgo, como el tamaño de la posición, niveles de stop-loss, y diversificación si aplica.
*   **Módulo de Logging y Reportes (Logger)**: Registrará todas las operaciones, decisiones, errores y métricas de rendimiento.
*   **(Opcional) Módulo de Comunicación IA (AICommunicator)**: Facilitará el intercambio de información con la IA de Windsurf mediante la lectura/escritura de un archivo específico.

## 3. Fases del Desarrollo

El proyecto se dividirá en las siguientes fases:

### Fase 1: Investigación y Diseño Detallado
*   **Objetivo**: Establecer una base sólida para el desarrollo.
*   **Tareas Clave**:
    *   Investigación exhaustiva de la API de Binance Futuros.
    *   Selección final de bibliotecas Python (GUI, Conectividad, Análisis).
    *   Diseño detallado de cada módulo.
    *   Creación del archivo `Tasks.md` con el desglose de tareas en 3 niveles.
    *   Definición detallada de las estrategias de trading y sus parámetros.
    *   Diseño del mecanismo de backtesting.
    *   Esbozo inicial de la interfaz de usuario.

### Fase 2: Desarrollo del Núcleo del Bot
*   **Objetivo**: Implementar la funcionalidad básica de conexión, obtención de datos y ejecución.
*   **Tareas Clave**:
    *   Desarrollo del `BinanceConnector` (autenticación, endpoints REST, conexión WebSocket).
    *   Desarrollo del `DataFetcher` (suscripción a streams de klines, libro de órdenes, trades).
    *   Desarrollo inicial del `OrderExecutor` (colocación y cancelación de órdenes básicas).
    *   Implementación del `Logger` básico.

### Fase 3: Implementación de Estrategias de Trading y Backtesting
*   **Objetivo**: Codificar y probar las estrategias de trading definidas.
*   **Tareas Clave**:
    *   Desarrollo del `StrategyEngine`.
    *   Implementación individual de cada estrategia:
        *   Monitoreo de indicadores y heurísticas.
        *   DCA (Dollar Cost Averaging) avanzado.
        *   Cobertura (Hedging) de operación inversa.
        *   Fibonacci circular en cascada/círculos concéntricos.
        *   Análisis y heurística de puntos pivote.
        *   Análisis y heurística de puntos de liquidez.
        *   Adaptación mecanizada a cambios de tendencia (con enfoque en macrotendencias).
    *   Desarrollo del `Backtester` (carga de datos históricos, simulación de trades, cálculo de métricas de rendimiento).
    *   Integración de estrategias con el `OrderExecutor` y `RiskManager` básico.

### Fase 4: Desarrollo de la Interfaz de Usuario (GUI)
*   **Objetivo**: Crear una interfaz gráfica funcional e intuitiva.
*   **Tareas Clave**:
    *   Selección e implementación del framework GUI (ej. Tkinter, PyQt).
    *   Diseño y desarrollo de las diferentes vistas:
        *   Dashboard principal (estado del bot, P&L, información de mercado).
        *   Configuración de parámetros del bot y estrategias.
        *   Visualización de gráficos de precios e indicadores.
        *   Monitor de órdenes y posiciones.
        *   Interfaz de Backtesting (configuración, ejecución, visualización de resultados).
    *   Integración de la GUI con los módulos del backend.

### Fase 5: Integración, Pruebas Exhaustivas y Refinamiento
*   **Objetivo**: Asegurar la robustez, fiabilidad y rendimiento del bot.
*   **Tareas Clave**:
    *   Integración completa de todos los módulos.
    *   Implementación y mejora del `RiskManager`.
    *   Pruebas unitarias para cada componente.
    *   Pruebas de integración del sistema completo.
    *   Pruebas de rendimiento y estrés.
    *   Ejecución de múltiples escenarios de backtesting y optimización de estrategias.
    *   Paper trading en la testnet de Binance Futuros.
    *   Corrección de errores y refinamiento de la lógica.

### Fase 6: (Opcional) Implementación de Comunicación con IA de Windsurf
*   **Objetivo**: Permitir el intercambio de datos con la IA de Windsurf.
*   **Tareas Clave**:
    *   Definición del formato del archivo de comunicación.
    *   Implementación de la lógica de lectura y escritura del archivo por parte del bot.
    *   Pruebas de la comunicación asincrónica.

### Fase 7: Documentación Final y Entrega
*   **Objetivo**: Preparar el proyecto para su uso y mantenimiento.
*   **Tareas Clave**:
    *   Revisión y finalización de `Plan.md` y `Tasks.md`.
    *   Creación de documentación técnica (arquitectura, configuración, APIs internas).
    *   Creación de un manual de usuario básico.
    *   Empaquetado del bot para Windows 10 (si es necesario).

## 4. Tecnologías Clave (Propuestas)

*   **Lenguaje de Programación**: Python 3.x
*   **Interfaz de Usuario (GUI)**:
    *   Opción 1: Tkinter (incluido en Python, más simple).
    *   Opción 2: PyQt o Kivy (más potentes y flexibles, pero con dependencias externas).
*   **Conexión API Binance**:
    *   `python-binance` (biblioteca popular para interactuar con Binance).
    *   `requests` (para llamadas HTTP REST).
    *   `websockets` (para comunicación en tiempo real).
*   **Análisis de Datos y Numérico**:
    *   Pandas (para manipulación y análisis de datos tabulares).
    *   NumPy (para operaciones numéricas eficientes).
    *   TA-Lib (biblioteca de análisis técnico, si se decide usar indicadores estándar).
*   **Backtesting**:
    *   Desarrollo propio utilizando Pandas y NumPy, o
    *   Bibliotecas como `Backtesting.py` o `bt` (a evaluar su complejidad y ajuste al proyecto).
*   **Base de Datos (Opcional, para datos históricos o logs extensos)**:
    *   SQLite (simple, basada en archivos).
*   **Control de Versiones**: Git

## 5. Consideraciones Adicionales

*   **Gestión de Riesgos**: Se priorizará la implementación de mecanismos robustos para mitigar pérdidas, incluyendo stop-loss dinámicos y control del tamaño de la posición.
*   **Seguridad**: Las claves API de Binance se almacenarán y manejarán de forma segura (ej. variables de entorno, configuración encriptada).
*   **Manejo de Errores y Resiliencia**: El bot deberá ser capaz de manejar errores de conexión, respuestas inesperadas de la API y otras excepciones de forma elegante, intentando reconexiones y registrando los problemas.
*   **Rendimiento**: Se optimizará el código para un procesamiento eficiente de datos en tiempo real y una toma de decisiones rápida, especialmente en el `DataFetcher` y `StrategyEngine`.
*   **Actualizaciones de la API de Binance**: La API de Binance puede cambiar. El diseño debe facilitar la adaptación a futuras actualizaciones.

Este plan servirá como una hoja de ruta para el desarrollo del proyecto y se actualizará según sea necesario a medida que avance el proyecto.
