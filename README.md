# off-key
Online Anomaly Detection with Uncertainty Quantification

---

## Project Structure

- **ev-charger-monitoring/**
  - **.github/**: GitHub Actions workflows for CI/CD.
  - **backend/**: Backend services.
    - **api/**: FastAPI/Flask application.
      - **endpoints/**: API endpoints (e.g., data ingestion, model management).
      - **middleware/**: Rate limiting, authentication, etc.
      - **models/**: Database models (SQLAlchemy, Pydantic).
      - **schemas/**: Pydantic schemas for request/response validation.
      - **utils/**: Utility functions (e.g., logging, error handling).
      - **main.py**: FastAPI/Flask entry point.
    - **ml/**: Machine learning layer.
      - **models/**: Online ML models (e.g., River, isolation forest).
      - **pipelines/**: Data preprocessing pipelines.
      - **registry/**: Model registry (configurations, metadata).
      - **tasks/**: Celery tasks for parallel execution.
    - **storage/**: Database and storage integration.
      - **migrations/**: Database migrations (Alembic).
      - **timeseries/**: InfluxDB/TimescaleDB integration.
      - **relational/**: PostgreSQL integration.
    - **config.py**: Configuration file (e.g., environment variables).
  - **frontend/**: Frontend application.
    - **public/**: Static assets (e.g., images, fonts).
    - **src/**: Next.js application.
      - **components/**: Reusable UI components (e.g., charts, anomaly indicators).
      - **pages/**: Next.js pages (e.g., dashboard, charger details).
      - **store/**: Redux Toolkit state management.
      - **styles/**: TailwindCSS or custom styles.
      - **utils/**: Utility functions (e.g., API calls, data formatting).
      - **_app.js**: Next.js app entry point.
    - **next.config.js**: Next.js configuration.
  - **infrastructure/**: Infrastructure as code.
    - **docker/**: Dockerfiles for backend, frontend, and ML.
    - **kubernetes/**: Kubernetes manifests for deployment.
    - **scripts/**: Deployment and setup scripts.
    - **terraform/**: Terraform scripts for cloud provisioning (optional).
  - **docs/**: Documentation.
    - **api/**: API documentation (Swagger/OpenAPI).
    - **mqtt/**: MQTT integration guide.
    - **ml/**: ML model documentation.
    - **user-guide/**: User guide for the dashboard.
  - **tests/**: Automated tests.
    - **backend/**: Backend unit and integration tests.
    - **frontend/**: Frontend unit and integration tests.
    - **ml/**: ML model validation tests.
  - **.env**: Environment variables (ignored in Git).
  - **.gitignore**: Git ignore file.
  - **README.md**: Project overview and setup instructions.
  - **requirements.txt**: Python dependencies (backend + ML).

### Explanation of the Structure

- **`.github/`:** Contains GitHub Actions workflows for CI/CD pipelines.
- **`backend/`:** Houses the backend logic, including API endpoints, ML models, and database integrations.
- **`frontend/`:** Contains the Next.js application with reusable components, pages, and state management.
- **`infrastructure/`:** Includes Dockerfiles, Kubernetes manifests, and deployment scripts.
- **`docs/`:** Stores documentation for APIs, MQTT integration, ML models, and user guides.
- **`tests/`:** Contains unit and integration tests for backend, frontend, and ML components.
- **`.env`:** Environment variables for local development (ignored in Git).
- **`.gitignore`:** Specifies files and directories to ignore in version control.
- **`README.md`:** Provides an overview of the project and setup instructions.
- **`requirements.txt`:** Lists Python dependencies for the backend and ML components.

---

## System Overview

The platform serves as a comprehensive monitoring and anomaly detection system for electric vehicle chargers, utilizing online machine learning for real-time analysis. This prototype is designed for research purposes with scalability in mind.

## Core Requirements

### Data Collection & Storage
- Real-time data ingestion from multiple sources:
  - Sampling frequency: 1-5 seconds per datastream
  - Data retention period: 2-4 weeks with automatic deletion
  - Basic data export functionality (CSV/Parquet)
  - Expected data volume: Few MB per day per datastream
  - Data format: Primarily JSON
  - Supported sensor types: temperature, voltage, current, and expandable
  - Support for both API and MQTT broker connections
- Basic data validation:
  - Handling of NA values from sensors
  - No specific requirements for handling data gaps

### Machine Learning Capabilities
- Implementation of online machine learning algorithms including:
  - Online isolation forest
  - Statistical models
  - Simple threshold-based detection
  - Extensible framework for additional algorithms
- User-configurable model parameters
- Model configuration access:
  - Limited to admin and model creator
  - No model creation limits per user
- Dynamic model management:
  - Support for adding/removing models during runtime
  - Frontend-backend synchronization for model changes
- Parallel execution of multiple ML models
- Real-time anomaly detection and flagging
- Simple model management:
  - No version control for model configurations
  - Models can be deleted and recreated with new configurations

### Frontend Features
- Minimalistic, clean design using shadcn
- Dashboard layout:
  - Overview page showing health status of all chargers (red/green indicators)
  - Individual pages for each time series
  - Dynamic page generation based on user's chargers and sensors
- Real-time and historical data visualization:
  - Single line chart per page
  - Anomaly visualization as transparent red background areas
  - Information boxes for anomaly details
  - Warning indicators for model failures (yellow warning sign)
  - Indication of data stream unavailability
- Drag-and-drop interface for ML model configuration
- Data source configuration interface with API rate limit settings
- User-specific configuration storage
- Responsive design for various screen sizes
- Browser compatibility:
  - Focus on Chrome compatibility
  - No specific requirements for other browsers

### Backend Architecture
- Flexible API/MQTT broker integration system
- Database storage for:
  - Raw sensor data
  - ML model outputs
  - Anomaly detection results
- User configuration persistence
- Basic authentication system
- API rate limiting system:
  - Configurable via dashboard
  - Enforced minimum rate limit
  - Per-data source configuration
- Simple system logging
- Graceful error handling:
  - Model failure warnings
  - Data stream interruption handling
- No backup/recovery system in first iteration

### Alerting
- Primary anomaly visualization in dashboard
- Potential for email alert integration in future iterations

## Scalability & Performance
- Initial scope:
  - 25-50 chargers
  - Multiple datastreams per charger
  - Support for 3+ concurrent users
- Design considerations for future scaling without major refactoring
- Independent monitoring of multiple datastreams per charger
- No specific internal performance metrics in first iteration

## Security Requirements
- Basic user authentication
- API authentication
- API key/credential management system
- Standard security practices implementation
- No specific requirements for sensitive data protection

## Future Considerations

### User Management
- Planned role-based access control:
  - Admin
  - Operator
  - Viewer
- Architecture should support easy implementation of user roles

### System Extensibility
- Support for adding new data sources
- Capability to integrate various API implementations
- Expandable ML algorithm library
- Documentation for API/MQTT integration

### Integration Requirements
- Documentation for API/MQTT integration required
- No testing/staging environment in first iteration

---

## Proposed Architecture

### 1. Data Collection & Ingestion Layer
- **API Gateway:** Handles API integrations, authentication, and rate limiting.
- **MQTT Broker:** For lightweight, high-frequency messaging (e.g., [Eclipse Mosquitto](https://mosquitto.org/)).
- **Ingestion Pipeline:** Use a lightweight stream processor (e.g., [Apache Flink](https://flink.apache.org/) or custom Python/Node.js scripts) to validate and preprocess incoming data.

### 2. Storage Layer
- **Time-Series Database:**
  - [InfluxDB](https://www.influxdata.com/) or [TimescaleDB](https://www.timescale.com/) for storing raw sensor data.
  - Configure data retention policies for automatic deletion after 2–4 weeks.
- **Relational Database:**
  - PostgreSQL for user configurations, metadata, and model parameters.
- **Object Storage:**
  - Use AWS S3 or MinIO for data export (CSV/Parquet).

### 3. Machine Learning Layer
- **Online ML Framework:**
  - Use [River](https://riverml.xyz/) for implementing online learning algorithms.
- **Orchestration:**
  - Use lightweight task managers like Celery or FastAPI workers for parallel ML model execution.
- **Model Management:**
  - Dynamically load models at runtime using Python scripts and store configurations in the database.

### 4. Backend Services
- **Framework:** FastAPI or Flask for RESTful API development.
- **Logging & Monitoring:** Use tools like ELK (Elasticsearch, Logstash, Kibana) or Fluentd for structured logging.
- **Authentication:** JWT-based authentication for users and API clients.

### 5. Frontend
- **Framework:** [Next.js](https://nextjs.org/) with ShadCN for a React-based design.
- **Visualization:**
  - Use [Chart.js](https://www.chartjs.org/) or [D3.js](https://d3js.org/) for line charts and anomaly visualizations.
- **State Management:** Use [Redux Toolkit](https://redux-toolkit.js.org/) for user-specific configurations.
- **Responsive Design:** TailwindCSS with Flexbox/Grid layouts for compatibility across devices.

### 6. Alerting
- **Real-Time Alerts:** WebSocket integration for anomaly alerts displayed on the dashboard.
- **Email Alerts:** Plan for integration in future iterations using task queues like Celery.

### 7. Scalability
- **Containerization:** Use Docker and orchestrate with Kubernetes for horizontal scaling.
- **Load Balancing:** Use Nginx or Traefik for API endpoint management.

---

## Tech Stack

| Component                       | Technology Recommendation                           |
|---------------------------------|-----------------------------------------------------|
| **Data Ingestion**              | MQTT (Eclipse Mosquitto), FastAPI, Apache Flink    |
| **Time-Series Storage**         | InfluxDB, TimescaleDB                              |
| **Relational Database**         | PostgreSQL                                         |
| **Machine Learning**            | Python (River, Scikit-learn for benchmarking)      |
| **Visualization**               | Next.js, ShadCN, D3.js/Chart.js                   |
| **Task Queue/Orchestration**    | Celery, RabbitMQ, or Redis                         |
| **Authentication**              | FastAPI OAuth2/JWT                                |
| **Containerization**            | Docker, Kubernetes                                |
| **Logging & Monitoring**        | ELK Stack, Prometheus/Grafana                     |

---

## Suggestions for Implementation

1. **Dynamic Model Management:** Use Python’s `joblib` for lightweight serialization and runtime loading of models. Maintain a model registry in the relational database.
2. **Rate Limiting:** Implement middleware in FastAPI or use a dedicated library to control API usage.
3. **Error Handling:** Wrap ML tasks in `try-except` blocks and log warnings for model failures or data stream interruptions.
4. **Frontend-Backend Sync:** Use WebSockets or server-sent events (SSE) for real-time synchronization between the dashboard and backend.
5. **Data Retention Policies:** Configure TTL (time-to-live) on time-series data directly within InfluxDB/TimescaleDB.
