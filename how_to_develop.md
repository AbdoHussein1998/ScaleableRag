












# Backend Development Standards

## Architecture Overview

The project follows a layered architecture based on **Dependency Injection**, **Service-Oriented Design**, and **Custom Exception Handling**.

The request lifecycle is illustrated below:

```text
HTTP Request
      │
      ▼
FastAPI Router
      │
      ▼
Dependency Module
      │
      ▼
Infrastructure Providers
      │
      ▼
Service
      │
      ▼
Business Logic
      │
      ▼
Custom Exceptions
      │
      ▼
HTTP Response
```

Each layer has a single responsibility.

---

# Naming Conventions

## Classes

All classes **must** follow the **CamelCase** naming convention.

Examples

```python
class MongoProvider:
    ...

class ArabicPdfProcessingService:
    ...

class WelcomeService:
    ...
```

---

# Infrastructure Components

Infrastructure components include:

* Database Providers
* LLM Providers
* Storage Providers
* API Clients
* Document Engines
* Embedding Models

Every infrastructure component must expose an asynchronous factory method named `init_class()`.

Example

```python
class MongoProvider:

    @classmethod
    async def init_class(
        cls,
        *args,
        **kwargs,
    ):
        return cls(*args, **kwargs)
```

The responsibility of `init_class()` is only to create and return an instance.

---

# Services

Every service must inherit from `ServiceInterface`.

```python
class ArabicPdfProcessingService(ServiceInterface):
    ...
```

Every service must implement

```python
@classmethod
async def init_service(...)
```

Example

```python
@classmethod
async def init_service(
    cls,
    document_engine,
    embedding_model,
    vector,
    json,
):
    return cls(
        document_engine=document_engine,
        embedding_model=embedding_model,
        vector=vector,
        json=json,
    )
```

The responsibility of `init_service()` is only to create and return a new service instance.

Services must never create providers or infrastructure components themselves.

---

# Constructor Dependency Injection

All dependencies must be injected through the constructor.

Example

```python
class ArabicPdfProcessingService(ServiceInterface):

    def __init__(
        self,
        document_engine,
        embedding_model,
        vector,
        json,
    ):
        self.document_engine = document_engine
        self.embedding_model = embedding_model
        self.vector = vector
        self.json = json
```

Never instantiate dependencies inside a service.

❌ Incorrect

```python
self.mongo = MongoProvider(...)
```

✅ Correct

```python
def __init__(
    self,
    mongo: MongoProvider,
):
    self.mongo = mongo
```

---

# Dependency Modules

Dependency modules are responsible for constructing the complete dependency graph.

Example

```
Dependencies/
    arabic_pdf_processing_dependency.py
    welcome_dependency.py
```

A dependency module is responsible for:

* Reading application settings
* Creating providers
* Creating infrastructure objects
* Creating services
* Returning the configured service

Example

```python
async def get_arabic_pdf_service():

    settings = get_basic_settings()

    mongo = await MongoProvider.init_class(...)

    vector = await QdrantProvider.init_class(...)

    embedding = ...

    document_engine = ...

    return await ArabicPdfProcessingService.init_service(
        document_engine=document_engine,
        embedding_model=embedding,
        vector=vector,
        json=mongo,
    )
```

Dependency modules are the **only** place where object construction should occur.

---

# API Routers

Routers should only be responsible for:

* Receiving HTTP requests
* Receiving dependencies using `Depends`
* Calling service methods
* Returning HTTP responses
* Handling exceptions

Routers must **not** contain business logic.

Example

```python
@router.post("/read_pdf")
async def read_pdf(
    service=Depends(get_arabic_pdf_service),
    file: UploadFile = File(...)
):

    result = await service.process(file)

    return result
```

The router remains clean because the service has already been fully configured by the dependency module.

---

# Exception Handling

Every service must define its own custom exception class.

Example

```python
class ArabicPdfProcessingError(Exception):

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
```

A custom exception represents expected business or domain errors.

Examples include:

* PDF processing failed
* Invalid document
* Embedding generation failed
* Database insertion failed

Custom exceptions make failures explicit and allow routers to return meaningful HTTP responses.

---

# Raising Exceptions

Services should raise only their own custom exception for expected failures.

Example

```python
if not extracted_text:
    raise ArabicPdfProcessingError(
        "No text extracted from PDF."
    )
```

Unexpected errors should be caught, logged, and wrapped inside the custom exception whenever appropriate.

---

# Exception Handling in Routers

Routers should translate service exceptions into HTTP responses.

Example

```python
try:

    result = await service.process(file)

    return JSONResponse(...)

except ArabicPdfProcessingError as e:

    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "message": e.message,
        },
    )

except Exception:

    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error",
        },
    )
```

This separation keeps business logic independent from the transport layer.

Services know nothing about HTTP, while routers know nothing about business logic.

---

# Layer Responsibilities

| Layer             | Responsibility                                  |
| ----------------- | ----------------------------------------------- |
| Router            | HTTP request/response handling                  |
| Dependency Module | Build and wire dependencies                     |
| Infrastructure    | External systems (Database, LLM, APIs, Storage) |
| Service           | Business logic                                  |
| Exception         | Represent business failures                     |

---

# Files and Folder naming 
* All files Folder Names Should be Captalized the firstletter only 
* All .py folders should be in small_snake_case
Example 

```
📦src
 ┣ 📂Api
 ┃ ┣ 📂ApiConfiguration
 ┃ ┃ ┣ 📜api_setting.py
 ┃ ┃ ┗ 📜fast_api_config.py
 ┃ ┗ 📂Routes
 ┃ ┃ ┗ 📂Client
 ┃ ┃ ┃ ┗ 📜basic_client_routes.py
 ┣ 📂DatabaseInfrastructure
 ┃ ┣ 📂Json
 ┃ ┃ ┣ 📂Mongodb
 ┃ ┃ ┃ ┣ 📜async_controller.py
 ┃ ┃ ┃ ┣ 📜Constants.py
 ┃ ┃ ┃ ┗ 📜__init__.py
 ┃ ┃ ┣ 📜json_interface.py
 ┃ ┃ ┗ 📜__init__.py
```


# Design Rules

* Classes must use **CamelCase**.
* Infrastructure components must implement `init_class()`.
* Services must inherit from `ServiceInterface`.
* Services must implement `init_service()`.
* Dependencies must be injected through constructors.
* Services must never instantiate other services or infrastructure.
* Dependency modules are the single composition root for object creation.
* Routers must not contain business logic.
* Every service must define a dedicated custom exception.
* Routers are responsible for converting exceptions into HTTP responses.
* Business logic must remain independent of the web framework.

Following these rules results in a modular, testable, maintainable, and extensible backend architecture where each layer has a single, well-defined responsibility.



