"""What to learn, in what order, and what "done" looks like (US-5.2).

Hand-curated, and it has to be. US-5.2 AC1 asks for a path *"ordered by dependency
(Docker before Kubernetes)"*, and nothing in the system knows that ordering:

- **`parent_skill_id` is categorisation, not prerequisite.** TypeScript is a child
  of JavaScript in the taxonomy because it belongs to that family. React is not a
  child of JavaScript, yet you cannot learn React first. The two relations look
  similar and mean different things, and using one for the other would produce
  confident nonsense.
- **Co-occurrence in job adverts is not pedagogy.** Postings asking for Kubernetes
  almost always ask for Docker, which is suggestive — but they also pair Python
  with AWS, and neither is a prerequisite for the other. Inferring what to study
  from what employers list together would dress a correlation up as teaching
  advice.

So this is a judgement list. It is small, checkable, and wrong in ways a reader
can see and argue with, which is the best property available when the alternative
is an unfalsifiable guess.

## Only curated skills become steps

A gap with no entry here produces **no step**, and the API says how many were
skipped rather than padding the path with "Learn Snowflake — 10 hours — be able
to use Snowflake". A generic outcome is not a concrete one (AC2), and filling a
study plan with sentences nobody wrote would make the useful steps harder to
trust.

Curation covers the skills the corpus actually asks for: every entry below
appeared in the demand ranking measured on 2026-09-12, most of them in more than
10% of live postings.

## Hours are rough, and labelled that way

`hours` is a study estimate for someone who already meets the prerequisites. It
is not measured — there is no dataset of how long people take — so the API calls
the field an estimate and the interface should present it as one. The numbers are
ordered sensibly relative to each other, which is the property that matters for
planning a sequence; their absolute accuracy is not claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LearningStep:
    """How to approach one skill.

    `outcome` is deliberately something a person can check they have done, not a
    restatement of the skill name. "Understand Docker" is not an outcome;
    "containerise a service and run it with docker compose" is.
    """

    #: Canonical taxonomy names that should come first.
    prerequisites: tuple[str, ...] = field(default_factory=tuple)
    #: Rough study hours for someone who already has the prerequisites.
    hours: int = 12
    outcome: str = ""


CURATED: dict[str, LearningStep] = {
    # ---------------------------------------------------------------- languages
    "Python": LearningStep(
        hours=40,
        outcome="Write a script that reads a file, transforms the data and writes the result.",
    ),
    "JavaScript": LearningStep(
        hours=40,
        outcome="Build a page that fetches from an API and renders the result without a framework.",
    ),
    "TypeScript": LearningStep(
        prerequisites=("JavaScript",),
        hours=20,
        outcome="Convert a small JavaScript project and remove every `any`.",
    ),
    "Java": LearningStep(
        hours=45,
        outcome="Build and run a command-line application with Maven or Gradle.",
    ),
    "SQL": LearningStep(
        hours=25,
        outcome="Answer a business question with a join, a group-by and a window function.",
    ),
    "Go": LearningStep(
        hours=30, outcome="Write an HTTP service with the standard library and no framework."
    ),
    "Scala": LearningStep(prerequisites=("Java",), hours=35, outcome="Write a Spark job in Scala."),
    # ---------------------------------------------------------------- web basics
    "HTML": LearningStep(
        hours=10, outcome="Build a page that is usable with the CSS switched off."
    ),
    "CSS": LearningStep(
        prerequisites=("HTML",),
        hours=20,
        outcome="Lay out a responsive page with flexbox and grid, no framework.",
    ),
    "React": LearningStep(
        prerequisites=("JavaScript",),
        hours=35,
        outcome="Build an app with routing, a form, and data loaded from an API.",
    ),
    "Redux": LearningStep(
        prerequisites=("React",), hours=12, outcome="Move one feature's state out of components."
    ),
    "Angular": LearningStep(
        prerequisites=("TypeScript",), hours=35, outcome="Build a routed app with a typed service."
    ),
    # ---------------------------------------------------------------- backend
    "REST API": LearningStep(
        hours=15,
        outcome="Design and document an API where the verbs and status codes are defensible.",
    ),
    "Django": LearningStep(
        prerequisites=("Python",),
        hours=35,
        outcome="Ship a CRUD app with migrations, auth and the admin enabled.",
    ),
    "Flask": LearningStep(
        prerequisites=("Python",), hours=18, outcome="Build a small API with blueprints and tests."
    ),
    "FastAPI": LearningStep(
        prerequisites=("Python", "REST API"),
        hours=20,
        outcome="Build an async API with Pydantic models and generated OpenAPI docs.",
    ),
    "Spring Boot": LearningStep(
        prerequisites=("Java",), hours=40, outcome="Build a REST service with dependency injection."
    ),
    "Node.js": LearningStep(
        prerequisites=("JavaScript",), hours=25, outcome="Build an Express API and test it."
    ),
    "Microservices": LearningStep(
        prerequisites=("REST API", "Docker"),
        hours=25,
        outcome="Split one app into two services and explain what the split cost you.",
    ),
    "GraphQL": LearningStep(
        prerequisites=("REST API",), hours=18, outcome="Expose a schema and resolve a nested query."
    ),
    # ---------------------------------------------------------------- data stores
    "PostgreSQL": LearningStep(
        prerequisites=("SQL",),
        hours=25,
        outcome="Design a schema with proper keys, then explain a slow query and fix it.",
    ),
    "MySQL": LearningStep(prerequisites=("SQL",), hours=20, outcome="Design and index a schema."),
    "MongoDB": LearningStep(
        hours=18, outcome="Model a document schema and explain when it beats a relational one."
    ),
    "Redis": LearningStep(
        hours=10, outcome="Cache an expensive endpoint and handle the invalidation."
    ),
    "NoSQL": LearningStep(
        prerequisites=("SQL",),
        hours=12,
        outcome="Explain which of your tables would be better as documents, and why.",
    ),
    "Elasticsearch": LearningStep(
        hours=20, outcome="Index a dataset and write a query with filters and aggregations."
    ),
    # ---------------------------------------------------------------- platform
    "Git": LearningStep(
        hours=12, outcome="Rebase a branch, resolve a conflict and recover a commit you lost."
    ),
    "GitHub": LearningStep(
        prerequisites=("Git",), hours=6, outcome="Open a pull request with a review and CI on it."
    ),
    "Linux": LearningStep(
        hours=20, outcome="Diagnose a process using too much memory on a machine you cannot reboot."
    ),
    "Docker": LearningStep(
        hours=20,
        outcome="Containerise a service and run it with docker compose alongside a database.",
    ),
    "Kubernetes": LearningStep(
        prerequisites=("Docker",),
        hours=45,
        outcome=(
            "Deploy a service with a readiness probe and roll out a new version "
            "without downtime."
        ),
    ),
    "CI/CD": LearningStep(
        prerequisites=("Git",),
        hours=15,
        outcome="Build a pipeline that runs tests and refuses to deploy when they fail.",
    ),
    "Terraform": LearningStep(
        hours=25, outcome="Describe an environment as code and apply a change without clicking."
    ),
    "AWS": LearningStep(
        hours=40,
        outcome="Run a containerised service with managed storage, and explain the bill.",
    ),
    "Microsoft Azure": LearningStep(
        hours=40, outcome="Run a containerised service and wire up managed identity."
    ),
    "Google Cloud Platform": LearningStep(
        hours=40, outcome="Run a containerised service and query data in BigQuery."
    ),
    "DevOps": LearningStep(
        prerequisites=("CI/CD", "Docker"),
        hours=20,
        outcome="Take one service from commit to production without a manual step.",
    ),
    # ---------------------------------------------------------------- data
    "ETL": LearningStep(
        prerequisites=("Python", "SQL"),
        hours=25,
        outcome="Build a pipeline that is safe to re-run after it fails halfway.",
    ),
    "Apache Airflow": LearningStep(
        prerequisites=("Python", "ETL"),
        hours=20,
        outcome="Schedule a DAG with retries and a backfill.",
    ),
    "Apache Spark": LearningStep(
        prerequisites=("Python", "SQL"),
        hours=35,
        outcome="Process a dataset too large for memory, and explain one shuffle you removed.",
    ),
    "Databricks": LearningStep(
        prerequisites=("Apache Spark",), hours=15, outcome="Run a Spark job on a managed cluster."
    ),
    "Snowflake": LearningStep(
        prerequisites=("SQL",), hours=18, outcome="Model a warehouse and explain a credit spike."
    ),
    "Apache Kafka": LearningStep(
        hours=25,
        outcome="Produce and consume a topic, and explain what happens when a consumer dies.",
    ),
    "Pandas": LearningStep(
        prerequisites=("Python",),
        hours=20,
        outcome="Clean a messy dataset and justify each choice.",
    ),
    "Data Analysis": LearningStep(
        prerequisites=("SQL",),
        hours=25,
        outcome="Answer a real question with data and state what would change your mind.",
    ),
    "Power BI": LearningStep(
        prerequisites=("SQL",), hours=18, outcome="Build a dashboard someone else can read unaided."
    ),
    "Tableau": LearningStep(
        prerequisites=("SQL",),
        hours=18,
        outcome="Build a dashboard with a defensible chart choice.",
    ),
    # ---------------------------------------------------------------- ml / ai
    "Machine Learning": LearningStep(
        prerequisites=("Python",),
        hours=60,
        outcome="Train a model, measure it honestly on held-out data, and beat a trivial baseline.",
    ),
    "Deep Learning": LearningStep(
        prerequisites=("Machine Learning",),
        hours=50,
        outcome="Train a network and explain why it overfits before it does.",
    ),
    "PyTorch": LearningStep(
        prerequisites=("Deep Learning",),
        hours=30,
        outcome="Write a training loop by hand, including the validation split.",
    ),
    "TensorFlow": LearningStep(
        prerequisites=("Deep Learning",), hours=30, outcome="Train and export a model for serving."
    ),
    "scikit-learn": LearningStep(
        prerequisites=("Machine Learning",),
        hours=15,
        outcome="Build a pipeline with cross-validation and no leakage.",
    ),
    "Natural Language Processing": LearningStep(
        prerequisites=("Machine Learning",),
        hours=30,
        outcome="Build a text classifier and explain where it fails.",
    ),
    "Large Language Models": LearningStep(
        prerequisites=("Python",),
        hours=25,
        outcome="Call a model from code, handle its failures, and measure the output quality.",
    ),
    "Prompt Engineering": LearningStep(
        prerequisites=("Large Language Models",),
        hours=12,
        outcome="Write an evaluation set, then improve a prompt against it rather than by feel.",
    ),
    "Generative AI": LearningStep(
        prerequisites=("Large Language Models",),
        hours=20,
        outcome="Ship a feature built on a model, with a fallback for when it is wrong.",
    ),
    "Embeddings": LearningStep(
        prerequisites=("Python",),
        hours=15,
        outcome="Embed a corpus and explain what the nearest neighbours get wrong.",
    ),
    "Vector Database": LearningStep(
        prerequisites=("Embeddings",),
        hours=12,
        outcome="Index a corpus and tune recall against latency with numbers.",
    ),
    "RAG": LearningStep(
        prerequisites=("Embeddings", "Large Language Models"),
        hours=25,
        outcome="Build retrieval-augmented answers and measure how often the source is wrong.",
    ),
    "LangChain": LearningStep(
        prerequisites=("Large Language Models",),
        hours=15,
        outcome="Build a chain with tools, and know what it costs per call.",
    ),
    "MLOps": LearningStep(
        prerequisites=("Machine Learning", "CI/CD"),
        hours=30,
        outcome="Deploy a model with versioning and a way to notice it degrading.",
    ),
    "OpenAI API": LearningStep(
        prerequisites=("Large Language Models",),
        hours=8,
        outcome="Use structured output and handle a rate limit without losing work.",
    ),
    # ---------------------------------------------------------------- practice
    "Agile": LearningStep(
        hours=8, outcome="Run a retrospective that changes something the following week."
    ),
    "Algorithms": LearningStep(
        hours=45,
        outcome="Explain the cost of your solution before writing it, and be right.",
    ),
    "System Design": LearningStep(
        prerequisites=("REST API",),
        hours=40,
        outcome="Design a system to a stated load and name what breaks first.",
    ),
    "Software Testing": LearningStep(
        hours=20,
        outcome="Write a test that fails for the right reason, then make it pass.",
    ),
}


def prerequisites_of(name: str) -> tuple[str, ...]:
    step = CURATED.get(name)
    return step.prerequisites if step else ()
