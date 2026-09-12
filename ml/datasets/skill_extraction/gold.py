"""Hand-written gold skill sets for `documents.jsonl` (ml.md section 2.4).

Each entry is the set of skills a reader would say the posting *asks for*,
written from the posting text alone and **before** looking at what the extractor
found. That order matters: reading the system's answer first turns labelling into
agreeing, and the resulting numbers would measure nothing.

## What counts as a skill here

- **Named technologies** — languages, frameworks, databases, cloud services,
  tools. Included whether required or nice-to-have; the requirement *level* is a
  separate question this dataset does not judge.
- **Named practices** — "Agile", "CI/CD", "code review", "unit testing" — when
  the posting names them, not when they are merely implied by the work.
- **Named soft skills** — "communication", "problem solving" — again only when
  written down. A posting that describes collaboration without naming it as a
  requirement does not get "Teamwork".

Deliberately excluded:

- Anything only in the **company blurb**. "We build AI-powered enterprise
  products" is marketing, not a requirement, and treating it as one is precisely
  the false positive that puts a skill on a candidate's profile they never
  claimed.
- Job titles, seniority, years of experience, degrees, locations.
- Skills a reader might *infer*. "Builds web applications" does not imply HTML.

## Names are written as the posting writes them

Not as the taxonomy spells them. The evaluator resolves each through the same
alias table the extractor uses, and anything that fails to resolve is counted
separately as **outside the taxonomy** — a ceiling on recall that no amount of
matcher tuning can lift. Folding those into the canonical spelling here would
hide exactly the number worth knowing.

**These labels are Claude-written and pending human review.** For relevance
judgement that would be a serious limitation; here it is a milder one, because
"does this posting name Kubernetes" has a defensible answer a second reader can
check against the text. `REVIEW.md` lists them for correction.
"""

from __future__ import annotations

GOLD: dict[int, list[str]] = {
    0: [
        "Python", "SQL", "PostgreSQL", "AWS", "Azure", "GCP", "Apache Airflow",
        "Prefect", "Apache Spark", "Databricks", "dbt", "Kafka", "Kinesis",
        "Git", "CI/CD", "ETL", "data warehousing", "dimensional modeling",
        "pandas", "PySpark", "data modeling",
    ],
    1: [
        "React", "Python", "Redux", "HTML", "CSS", "JavaScript", "TypeScript",
        "Django", "Flask", "FastAPI", "Bootstrap", "Material-UI", "Tailwind CSS",
        "REST API", "microservices", "JWT", "OAuth", "PostgreSQL", "MySQL",
        "SQL Server", "MongoDB", "SQL", "Git", "GitHub", "GitLab", "Bitbucket",
        "Docker", "AWS", "Azure", "GCP", "Jenkins", "GitHub Actions",
        "Azure DevOps", "Agile", "Scrum", "CI/CD", "responsive design",
        "code review", "React Hooks", "NoSQL",
    ],
    2: ["Python", "Node.js", "REST API", "MySQL", "PostgreSQL"],
    3: [
        "Java", "React", "REST API", "SOAP", "RPC", "Spring", "Spring Boot",
        "distributed systems", "data modeling", "DevOps", "communication",
        "problem solving", "MongoDB", "Redis", "MySQL", "microservices",
        "TCP/UDP", "SIP", "WebRTC", "ISDN", "testing", "monitoring", "debugging",
    ],
    4: [
        "Python", "LLM", "OpenAI", "Anthropic", "Google Gemini", "transformers",
        "tokenization", "vLLM", "TGI", "Ollama", "async programming",
        "embeddings", "semantic search", "Llama", "Mistral", "Qwen",
        "model distillation", "quantization", "prompt engineering",
        "machine learning",
    ],
    5: [
        "Apache Spark", "Scala", "SQL", "Azure Synapse", "GitHub",
        "Microsoft Fabric", "Java", "data warehousing", "ETL",
        "data integration",
    ],
    6: [
        "Python", "Jupyter", "data analysis", "problem solving",
        "communication", "debugging",
    ],
    7: [
        "Django", "Django REST Framework", "Python", "MySQL", "Elasticsearch",
        "WebSockets", "JavaScript", "JIRA", "GitLab", "REST API", "GCP", "AWS",
        "unit testing", "Agile", "communication", "debugging", "blockchain",
        "Flask",
    ],
    # A fixture posting, not a scraped one. Kept because a short, plainly worded
    # description is a real shape and the extractor should get it exactly right.
    8: ["Python", "PostgreSQL"],
    9: [
        "Python", "Django", "Flask", "GCP", "AWS", "Terraform", "FastAPI",
        "SQLAlchemy", "REST API", "GraphQL", "PostgreSQL", "MySQL", "Redis",
        "Celery", "RabbitMQ", "Docker", "Kubernetes", "CI/CD", "OAuth", "JWT",
        "Pytest", "TDD",
    ],
    10: [
        "Python", "machine learning", "deep learning", "generative AI", "LLM",
        "prompt engineering", "LangChain", "LlamaIndex", "Hugging Face",
        "PyTorch", "TensorFlow", "OpenAI", "Azure OpenAI", "RAG",
        "vector databases", "embeddings", "REST API", "microservices", "Git",
        "CI/CD", "Agile", "MLOps", "NLP", "computer vision", "DevOps",
        "distributed computing",
    ],
    11: [
        "machine learning", "deep learning", "NLP", "time series forecasting",
        "recommendation systems", "gradient boosting", "generative AI", "LLM",
        "prompt engineering", "RAG", "LoRA", "CI/CD", "statistics",
        "data science", "DevOps",
    ],
    12: [
        "Python", "generative AI", "REST API", "SQL", "NoSQL", "Kubernetes",
        "LangChain", "LangSmith", "LLM", "OpenAI", "Anthropic", "Mistral",
        "React", "Angular", "debugging", "problem solving", "networking",
    ],
    13: [
        "generative AI", "machine learning", "data analysis", "deep learning",
        "Python", "cloud computing", "LLM", "NLP", "artificial intelligence",
        "prompt engineering",
    ],
    # Almost no technical content: a generic internship advert whose only named
    # skills are two soft ones. Kept deliberately — a posting with nothing to
    # find is where a gazetteer's false positives show up most clearly.
    14: ["communication", "teamwork", "prompt engineering"],
    15: [
        "Python", "SQL", "FastAPI", "REST API", "Agile", "Scikit-learn",
        "TensorFlow", "PyTorch", "Keras", "feature engineering", "LLM",
        "prompt engineering", "RAG", "LangChain", "LangGraph", "OpenAI",
        "Hugging Face", "LangSmith", "Pinecone", "FAISS", "embeddings",
        "semantic search", "AWS", "SageMaker", "Docker", "Git", "JIRA",
        "CI/CD", "machine learning", "deep learning", "NLP", "generative AI",
        "vector databases",
    ],
    # This posting carries an HR system's category dump under a heading reading
    # "Required Skills": Semiconductors, Commercial Sales, Executive Presence,
    # Inclusion, Manufacturing Equipment. They are excluded. No reader would say
    # a lead data engineering role requires Semiconductors, and a gold set that
    # accepted them would reward an extractor for repeating boilerplate.
    16: [
        "ETL", "data pipelines", "Big Data", "data quality", "data analysis",
        "Agile", "cloud computing", "Databricks", "Snowflake", "Apache Spark",
        "Azure", "Oracle", "data engineering",
    ],
    17: [
        "Python", "LLM", "Anthropic", "LangChain", "LlamaIndex", "DSPy",
        "CrewAI", "REST API", "GitHub", "Slack", "Jira", "PagerDuty", "CI/CD",
        "BigQuery", "prompt engineering", "monitoring", "SRE",
    ],
    18: [
        "machine learning", "LLM", "RAG", "prompt engineering", "Kubernetes",
        "gRPC", "REST API", "microservices", "distributed systems", "SQL",
        "NoSQL", "PostgreSQL", "Redis", "Elasticsearch", "CI/CD",
        "test automation", "Terraform", "Helm", "data engineering", "GPU",
    ],
    19: [
        "Python", "C++", "CUDA", "PyTorch", "Hugging Face", "vLLM", "SGLang",
        "TensorRT-LLM", "NCCL", "Docker", "Kubernetes", "GPU", "quantization",
        "LoRA", "distributed computing", "MLOps", "CI/CD", "monitoring",
        "TensorRT", "DeepSpeed", "transformers", "LLM", "generative AI",
    ],
    20: [
        "Python", "FastAPI", "Flask", "Django REST Framework", "REST API",
        "async programming", "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQL",
        "NoSQL", "microservices", "Docker", "CI/CD", "Git", "problem solving",
        "communication", "code review", "AWS", "GCP", "Azure", "RabbitMQ",
        "Kafka", "Terraform", "CloudFormation", "Agile", "Scrum",
    ],
    21: [
        "prompt engineering", "RAG", "LLM", "generative AI", "Azure", "MLOps",
        "Python", "SQL", "machine learning", "time series analysis", "NLP",
        "transformers", "LLMOps", "Agile", "statistics",
    ],
    22: [
        "Angular", "JavaScript", "HTML", "Node.js", "Go", "Git", "REST API",
        "unit testing", "Cypress", "debugging", "AWS", "CI/CD", "teamwork",
    ],
    23: [
        "Python", "Django", "Django REST Framework", "SQL", "PostgreSQL",
        "MySQL", "REST API", "Git", "HTML", "CSS", "JavaScript", "Power BI",
        "DAX", "Power Query", "Docker", "FastAPI", "Azure", "AWS", "Redis",
        "Celery", "React", "Angular", "CI/CD", "Azure DevOps", "code review",
    ],
    24: [
        "computer vision", "LLM", "generative AI", "machine learning",
        "artificial intelligence",
    ],
    25: [
        "Python", "REST API", "JSON", "Flask", "FastAPI", "Django", "SQL",
        "MySQL", "PostgreSQL", "Git", "Docker", "Linux", "debugging",
        "communication", "teamwork", "problem solving",
    ],
    26: [
        "machine learning", "predictive analytics", "NLP", "statistics",
        "data modeling", "data visualization", "information retrieval",
        "communication", "analytical skills", "attention to detail",
    ],
    27: [
        "Python", "Java", "C#", "Node.js", "REST API", "AWS", "Azure", "GCP",
        "SQL", "NoSQL", "Docker", "Kubernetes", "machine learning", "CI/CD",
        "microservices", "distributed systems", "Jira", "Azure DevOps",
        "Confluence", "Power BI", "Tableau", "data pipelines",
    ],
    28: [
        "CI/CD", "MLOps", "DevOps", "Azure", "AWS", "GCP", "Terraform",
        "CloudFormation", "Ansible", "Docker", "Kubernetes", "Apache Spark",
        "Databricks", "Python", "monitoring", "machine learning",
    ],
    29: [
        "generative AI", "LLM", "machine learning", "prompt engineering", "RAG",
        "vector databases", "OpenAI", "Azure OpenAI", "Anthropic", "LangChain",
        "LangGraph", "LlamaIndex", "Semantic Kernel", "Python", "Azure", "AWS",
        "GCP",
    ],
}
