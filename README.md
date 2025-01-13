# off-key
Online Anomaly Detection with Uncertainty Quantification

---

# Project Setup on macOS

## 1. Prerequisites
Before starting, ensure you have the following installed on your macOS machine:
1. **Docker Desktop**: Install Docker Desktop for macOS from [here](https://www.docker.com/products/docker-desktop/).
2. **Homebrew**: Install Homebrew (a package manager for macOS) if you don’t already have it:
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
3. **Git**: Install Git using Homebrew:
   brew install git
4. **Node.js**: Install Node.js using Homebrew:
   brew install node

## 2. Clone the Project
Open the Terminal and clone the project repository:
git clone https://github.com/your-repo/timeflux-dashboard.git
cd timeflux-dashboard

## 3. Start Docker Desktop
1. Open Docker Desktop from your Applications folder.
2. Ensure Docker is running (you should see the Docker icon in the menu bar).

## 4. Run the Project with Docker Compose
In the Terminal, navigate to the project directory and run:
docker-compose up --build

This will:
1. Build the Docker images for the backend and frontend.
2. Start the TimescaleDB container.
3. Start the backend and frontend containers.

## 5. Access the Services
Once the containers are running, you can access the services in your browser:
- **Frontend Dashboard**: Open http://localhost:3000.
- **Backend API**: Open http://localhost:8000/data.

## 6. Stopping the Project
To stop the project, press Ctrl + C in the Terminal where docker-compose is running. Then, run:
docker-compose down
This will stop and remove the containers.

## 7. Debugging Tips
### a. Check Docker Logs
If a service fails to start, check the logs using:
docker-compose logs <service_name>
For example:
docker-compose logs backend

### b. Port Conflicts
Ensure no other application is using ports 3000 (frontend), 8000 (backend), or 5432 (TimescaleDB). You can change the ports in the docker-compose.yml file if needed.

### c. Docker Desktop Resource Allocation
If the containers are slow or unresponsive, increase the resources allocated to Docker Desktop:
1. Open Docker Desktop.
2. Go to Settings > Resources.
3. Increase CPU and memory allocation.

## 8. Running the Backend Outside Docker (Optional)
If you want to run the backend Python scripts outside Docker (e.g., for debugging), follow these steps:
1. Navigate to the backend directory:
   cd backend
2. Create a virtual environment and install dependencies:
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
3. Run the backend service:
   uvicorn api.main:app --reload

## 9. Running the Frontend Outside Docker (Optional)
If you want to run the frontend React app outside Docker, follow these steps:
1. Navigate to the frontend directory:
   cd frontend
2. Install dependencies:
   npm install
3. Run the frontend app:
   npm run dev

## 10. Project Structure
Here’s a quick overview of the project structure:
- **timeflux-dashboard/**
  - **backend/**
    - **api/**
      - `main.py`          # FastAPI app to serve data to frontend
    - **services/**
      - `data_fetcher.py`  # Fetches data from external API
      - `db_client.py`     # Handles TimescaleDB operations
    - `requirements.txt`
  - **frontend/**
    - **src/**
      - **pages/**
        - `Dashboard.jsx`  # Main dashboard page
    - `package.json`
  - `docker-compose.yml`
  - `README.md`

## 11. Next Steps
- Add authentication to the API.
- Improve error handling and logging.
- Deploy the project using Kubernetes or a cloud provider.

## 12. Conclusion
Setting up this project on macOS is straightforward thanks to its native support for Docker and Unix-based tools. If you encounter any issues, feel free to ask for help! 🚀

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

### **5. Frontend**
The frontend will be built using modern tools and frameworks to ensure a **responsive**, **scalable**, and **user-friendly** interface. Below are the specific recommendations:

#### **Framework**
- **[Next.js](https://nextjs.org/)**
  - A React-based framework that supports server-side rendering (SSR), static site generation (SSG), and API routes.
  - Perfect for building production-ready applications with SEO and performance in mind.
  - Integrates seamlessly with **shadcn/ui** for pre-built, customizable React components.

#### **UI Components**
- **[shadcn/ui](https://ui.shadcn.com/)**
  - A collection of beautifully designed, accessible, and customizable React components.
  - Works well with **Tailwind CSS** for rapid styling and theming.

#### **Visualization**
- **[Chart.js](https://www.chartjs.org/)**
  - A simple and flexible library for creating basic charts like line charts, bar charts, and pie charts.
  - Great for quick prototyping and visualizing anomaly detection results.
- **[D3.js](https://d3js.org/)**
  - A powerful library for creating complex, interactive, and custom data visualizations.
  - Ideal for advanced use cases where fine-grained control over visualizations is required.
- **[Recharts](https://recharts.org/)**
  - A React-specific charting library that integrates well with React and shadcn/ui.
  - Offers a balance between simplicity and customization.

#### **State Management**
- **[Redux Toolkit](https://redux-toolkit.js.org/)**
  - The official, opinionated toolset for efficient Redux development.
  - Ideal for managing global state, such as user-specific configurations and application settings.
- **[Zustand](https://zustand-demo.pmnd.rs/)**
  - A lightweight alternative to Redux for simpler state management needs.
  - Perfect for small to medium-sized applications.

#### **Styling and Responsive Design**
- **[Tailwind CSS](https://tailwindcss.com/)**
  - A utility-first CSS framework that enables rapid development of responsive and modern UIs.
  - Works seamlessly with **Flexbox** and **CSS Grid** for creating flexible layouts.
- **[shadcn/ui](https://ui.shadcn.com/)**
  - Provides pre-built, responsive components that are easy to customize using Tailwind CSS.

#### **API Integration**
- **[Axios](https://axios-http.com/)**
  - A popular HTTP client for making API requests to your FastAPI backend.
  - Supports features like interceptors, request cancellation, and error handling.
- **[React Query](https://tanstack.com/query/v3/)**
  - A powerful library for managing server state, caching, and data synchronization.
  - Simplifies data fetching and improves performance.

#### **Testing**
- **[Jest](https://jestjs.io/)**
  - A JavaScript testing framework for unit and integration testing.
- **[React Testing Library](https://testing-library.com/docs/react-testing-library/intro/)**
  - A lightweight solution for testing React components in a way that mimics user behavior.
- **[Cypress](https://www.cypress.io/)**
  - An end-to-end testing framework for testing user interactions and workflows.

#### **Deployment**
- **[Vercel](https://vercel.com/)**
  - A platform for deploying Next.js applications with zero configuration.
  - Offers automatic CI/CD, preview deployments, and scalability.
- **[Netlify](https://www.netlify.com/)**
  - An alternative to Vercel with similar features for deploying static sites and serverless functions.

---

### **Example Workflow**
1. **Set up Next.js** with shadcn/ui and Tailwind CSS:
 ```bash
 npx create-next-app@latest my-app
 cd my-app
 npx shadcn-ui@latest init
 npm install tailwindcss postcss autoprefixer
 npx tailwindcss init -p
 ```
   
```bash
npm install recharts
```

```bash
npm install @reduxjs/toolkit react-redux
```

```bash
npm install -g vercel
vercel
```

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
| **Frontend Framework**          | Next.js                                           |
| **UI Components**               | ShadCN                                            |
| **Styling**                     | Tailwind CSS                                      |
| **State Management**            | Redux Toolkit, Zustand                            |
| **API Integration**             | Axios, React Query                                |
| **Testing**                     | Jest, React Testing Library, Cypress              |
| **Deployment**                  | Vercel, Netlify                                   |
| **CI/CD**                       | GitHub Actions, GitLab CI/CD                      |
| **Documentation**               | Swagger UI (FastAPI), Storybook (Frontend)        |
| **Data Visualization Libraries**| Recharts, Plotly.js, ApexCharts                   |
| **Real-Time Communication**     | WebSockets (FastAPI), Socket.IO                   |
| **Configuration Management**    | Hydra (Python), dotenv (Node.js)                  |
| **Security**                    | FastAPI Security Middleware, Helmet (Node.js)     |
| **Data Validation**             | Pydantic (FastAPI), Zod (Frontend)                |
| **Error Tracking**              | Sentry, LogRocket                                 |
| **Performance Optimization**    | Redis Cache, CDN (e.g., Cloudflare)               |
| **Version Control**             | Git (GitHub, GitLab, or Bitbucket)                |
| **Infrastructure as Code**      | Terraform, Pulumi                                 |
| **Cloud Providers**             | AWS, GCP, Azure, or DigitalOcean                  |
| **Data Pipeline Orchestration** | Apache Airflow, Prefect                           |
| **Edge Computing**              | FastAPI with ASGI (e.g., Uvicorn)                 |
| **Data Versioning**             | DVC (Data Version Control)                        |
| **Model Deployment**            | FastAPI, TensorFlow Serving, or TorchServe        |
| **API Gateway**                 | NGINX, Traefik                                    |
| **Data Privacy**                | GDPR Compliance Tools, Anonymization Libraries    |
| **Data Backup**                 | AWS S3, Google Cloud Storage                      |
| **Data Transformation**         | Pandas, NumPy, or Polars                          |
| **Data Governance**             | Apache Atlas, Amundsen                            |
| **Data Quality**                | Great Expectations, Deequ                         |
| **Data Lineage**                | OpenLineage, Marquez                              |
| **Data Catalog**                | DataHub, Amundsen                                 |
| **Data Exploration**            | Jupyter Notebooks, Streamlit                      |
| **Data Annotation**             | Label Studio, Prodigy                             |
| **Data Augmentation**           | Albumentations, Imgaug                            |
| **Model Monitoring**            | Evidently AI, WhyLabs                             |
| **Model Explainability**        | SHAP, LIME                                        |
| **Model Optimization**          | Optuna, Ray Tune                                  |
| **Model Serving**               | FastAPI, BentoML, or MLflow                       |
| **Edge AI**                     | TensorFlow Lite, ONNX Runtime                     |
| **Data Streaming**              | Apache Kafka, Apache Pulsar                       |
| **Data Warehousing**            | Snowflake, BigQuery                               |
| **Data Lakes**                  | Apache Iceberg, Delta Lake                        |
| **Data Integration**            | Apache NiFi, Talend                               |
| **Data Governance**             | Collibra, Alation                                 |
| **Data Security**               | Vault by HashiCorp, AWS KMS                       |
| **Data Compliance**             | Immuta, Privacera                                 |
| **Data Observability**          | Monte Carlo, Datafold                             |
| **Data Collaboration**          | Databricks, Snowflake                             |
| **Data Science Workflow**       | MLflow, Kubeflow                                  |
| **Data Engineering Workflow**   | Apache Airflow, Prefect                           |
| **DataOps**                     | DataKitchen, Great Expectations                   |
| **MLOps**                       | MLflow, Kubeflow, TFX                             |
| **AIOps**                       | Moogsoft, BigPanda                                |
| **DevOps**                      | Jenkins, GitLab CI/CD, CircleCI                   |
| **GitOps**                      | ArgoCD, Flux                                      |
| **Observability**               | OpenTelemetry, Grafana Tempo                      |
| **Incident Management**         | PagerDuty, Opsgenie                               |
| **Collaboration Tools**         | Slack, Microsoft Teams                            |
| **Project Management**          | Jira, Trello, Asana                               |
| **Documentation Tools**         | Confluence, Notion, MkDocs                        |
| **Code Quality**                | SonarQube, CodeClimate                            |
| **Static Analysis**             | ESLint, Prettier, Black (Python)                  |
| **Dynamic Analysis**            | Selenium, Cypress                                 |
| **Performance Testing**         | JMeter, k6                                        |
| **Load Testing**                | Locust, Gatling                                   |
| **Security Testing**            | OWASP ZAP, Burp Suite                             |
| **API Testing**                 | Postman, Insomnia                                 |
| **Data Testing**                | Great Expectations, Deequ                         |
| **Model Testing**               | Evidently AI, WhyLabs                             |
| **Compliance Testing**          | Vault by HashiCorp, AWS Config                    |
| **Disaster Recovery**           | AWS Backup, Google Cloud DR                       |
| **High Availability**           | Kubernetes, AWS Elastic Beanstalk                 |
| **Scalability**                 | Kubernetes, AWS Auto Scaling                      |
| **Cost Management**             | AWS Cost Explorer, Google Cloud Billing           |
| **Resource Optimization**       | Spot Instances, Reserved Instances                |
| **Data Archiving**              | AWS Glacier, Google Coldline                      |
| **Data Retention**              | Apache Ranger, AWS Lake Formation                 |
| **Data Governance**             | Apache Atlas, Amundsen                            |
| **Data Lineage**                | OpenLineage, Marquez                              |
| **Data Catalog**                | DataHub, Amundsen                                 |
| **Data Exploration**            | Jupyter Notebooks, Streamlit                      |
| **Data Annotation**             | Label Studio, Prodigy                             |
| **Data Augmentation**           | Albumentations, Imgaug                            |
| **Model Monitoring**            | Evidently AI, WhyLabs                             |
| **Model Explainability**        | SHAP, LIME                                        |
| **Model Optimization**          | Optuna, Ray Tune                                  |
| **Model Serving**               | FastAPI, BentoML, or MLflow                       |
| **Edge AI**                     | TensorFlow Lite, ONNX Runtime                     |
| **Data Streaming**              | Apache Kafka, Apache Pulsar                       |
| **Data Warehousing**            | Snowflake, BigQuery                               |
| **Data Lakes**                  | Apache Iceberg, Delta Lake                        |
| **Data Integration**            | Apache NiFi, Talend                               |
| **Data Governance**             | Collibra, Alation                                 |
| **Data Security**               | Vault by HashiCorp, AWS KMS                       |
| **Data Compliance**             | Immuta, Privacera                                 |
| **Data Observability**          | Monte Carlo, Datafold                             |
| **Data Collaboration**          | Databricks, Snowflake                             |
| **Data Science Workflow**       | MLflow, Kubeflow                                  |
| **Data Engineering Workflow**   | Apache Airflow, Prefect                           |
| **DataOps**                     | DataKitchen, Great Expectations                   |
| **MLOps**                       | MLflow, Kubeflow, TFX                             |
| **AIOps**                       | Moogsoft, BigPanda                                |
| **DevOps**                      | Jenkins, GitLab CI/CD, CircleCI                   |
| **GitOps**                      | ArgoCD, Flux                                      |
| **Observability**               | OpenTelemetry, Grafana Tempo                      |
| **Incident Management**         | PagerDuty, Opsgenie                               |
| **Collaboration Tools**         | Slack, Microsoft Teams                            |
| **Project Management**          | Jira, Trello, Asana                               |
| **Documentation Tools**         | Confluence, Notion, MkDocs                        |
| **Code Quality**                | SonarQube, CodeClimate                            |
| **Static Analysis**             | ESLint, Prettier, Black (Python)                  |
| **Dynamic Analysis**            | Selenium, Cypress                                 |
| **Performance Testing**         | JMeter, k6                                        |
| **Load Testing**                | Locust, Gatling                                   |
| **Security Testing**            | OWASP ZAP, Burp Suite                             |
| **API Testing**                 | Postman, Insomnia                                 |
| **Data Testing**                | Great Expectations, Deequ                         |
| **Model Testing**               | Evidently AI, WhyLabs                             |
| **Compliance Testing**          | Vault by HashiCorp, AWS Config                    |
| **Disaster Recovery**           | AWS Backup, Google Cloud DR                       |
| **High Availability**           | Kubernetes, AWS Elastic Beanstalk                 |
| **Scalability**                 | Kubernetes, AWS Auto Scaling                      |
| **Cost Management**             | AWS Cost Explorer, Google Cloud Billing           |
| **Resource Optimization**       | Spot Instances, Reserved Instances                |
| **Data Archiving**              | AWS Glacier, Google Coldline                      |
| **Data Retention**              | Apache Ranger, AWS Lake Formation                 |

---

## Suggestions for Implementation

1. **Dynamic Model Management:** Use Python’s `joblib` for lightweight serialization and runtime loading of models. Maintain a model registry in the relational database.
2. **Rate Limiting:** Implement middleware in FastAPI or use a dedicated library to control API usage.
3. **Error Handling:** Wrap ML tasks in `try-except` blocks and log warnings for model failures or data stream interruptions.
4. **Frontend-Backend Sync:** Use WebSockets or server-sent events (SSE) for real-time synchronization between the dashboard and backend.
5. **Data Retention Policies:** Configure TTL (time-to-live) on time-series data directly within InfluxDB/TimescaleDB.
