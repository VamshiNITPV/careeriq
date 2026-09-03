"""Seed skill taxonomy.

The alias lists are the point of this file. Matching a resume's "Postgres" to a
job's "PostgreSQL" is the entire job of the taxonomy, and it happens by
resolving both to one canonical id before any comparison — so every downstream
score compares ids, not strings (database.md section 3.2).

Aliases are stored normalised (lowercase, no punctuation) because that is the
form the extractor looks up. `normalize_skill_text` is the single definition of
that transformation; anything that writes an alias must go through it.

Parents encode implication: React implies JavaScript, so a React developer is
not scored as having no JavaScript at all (ml.md section 4.1).

This is a starting set, not a finished one. Extraction can create unverified
skills, and Phase 5 will grow it from the job corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PUNCTUATION = re.compile(r"[^\w+#.\s-]")
_WHITESPACE = re.compile(r"\s+")


def normalize_skill_text(value: str) -> str:
    """Canonical lookup form for a skill name or alias.

    Keeps `+`, `#` and `.` because they are load-bearing in real skill names —
    stripping them collapses C++ into C, C# into C, and .NET into net.
    """
    lowered = value.strip().lower()
    lowered = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", lowered).strip()


@dataclass(frozen=True, slots=True)
class SeedSkill:
    name: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    parent: str | None = None

    @property
    def normalized_name(self) -> str:
        return normalize_skill_text(self.name)

    @property
    def normalized_aliases(self) -> list[str]:
        # De-duplicated, and never containing the canonical form itself — that
        # is matched separately, and duplicating it inflates the GIN index.
        seen = {self.normalized_name}
        result: list[str] = []
        for alias in self.aliases:
            normalized = normalize_skill_text(alias)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


LANGUAGE = "language"
FRAMEWORK = "framework"
DATABASE = "database"
CLOUD = "cloud"
TOOL = "tool"
PRACTICE = "practice"
SOFT = "soft_skill"


SEED_SKILLS: tuple[SeedSkill, ...] = (
    # ---------------------------------------------------------------- languages
    SeedSkill("Python", LANGUAGE, ("python3", "python 3", "py")),
    SeedSkill("JavaScript", LANGUAGE, ("js", "ecmascript", "es6", "es2015")),
    SeedSkill("TypeScript", LANGUAGE, ("ts",), parent="JavaScript"),
    SeedSkill("Java", LANGUAGE, ("java8", "java 8", "java11", "java 17")),
    SeedSkill("C++", LANGUAGE, ("cpp", "c plus plus")),
    SeedSkill("C", LANGUAGE, ("c language",)),
    SeedSkill("C#", LANGUAGE, ("csharp", "c sharp")),
    SeedSkill("Go", LANGUAGE, ("golang",)),
    SeedSkill("Rust", LANGUAGE),
    SeedSkill("Ruby", LANGUAGE),
    SeedSkill("PHP", LANGUAGE),
    SeedSkill("Swift", LANGUAGE),
    SeedSkill("Kotlin", LANGUAGE),
    SeedSkill("Scala", LANGUAGE),
    SeedSkill("R", LANGUAGE, ("r language",)),
    SeedSkill("MATLAB", LANGUAGE),
    SeedSkill("Bash", LANGUAGE, ("shell", "shell scripting", "sh", "zsh")),
    SeedSkill("SQL", LANGUAGE),
    SeedSkill("HTML", LANGUAGE, ("html5",)),
    SeedSkill("CSS", LANGUAGE, ("css3",)),
    SeedSkill("Dart", LANGUAGE),
    SeedSkill("Perl", LANGUAGE),
    # ---------------------------------------------------------------- frontend
    SeedSkill("React", FRAMEWORK, ("reactjs", "react.js"), parent="JavaScript"),
    SeedSkill("Next.js", FRAMEWORK, ("nextjs", "next js"), parent="React"),
    SeedSkill("Vue.js", FRAMEWORK, ("vue", "vuejs"), parent="JavaScript"),
    SeedSkill("Angular", FRAMEWORK, ("angularjs", "angular 2"), parent="TypeScript"),
    SeedSkill("Svelte", FRAMEWORK, ("sveltekit",), parent="JavaScript"),
    SeedSkill("Redux", FRAMEWORK, parent="React"),
    SeedSkill("Tailwind CSS", FRAMEWORK, ("tailwind", "tailwindcss"), parent="CSS"),
    SeedSkill("Bootstrap", FRAMEWORK, parent="CSS"),
    SeedSkill("Sass", FRAMEWORK, ("scss",), parent="CSS"),
    SeedSkill("jQuery", FRAMEWORK, parent="JavaScript"),
    SeedSkill("Webpack", TOOL),
    SeedSkill("Vite", TOOL),
    # ---------------------------------------------------------------- backend
    SeedSkill("Node.js", FRAMEWORK, ("node", "nodejs"), parent="JavaScript"),
    SeedSkill("Express.js", FRAMEWORK, ("express", "expressjs"), parent="Node.js"),
    SeedSkill("NestJS", FRAMEWORK, ("nest js",), parent="Node.js"),
    SeedSkill("Django", FRAMEWORK, parent="Python"),
    SeedSkill("Flask", FRAMEWORK, parent="Python"),
    SeedSkill("FastAPI", FRAMEWORK, ("fast api",), parent="Python"),
    SeedSkill("Spring Boot", FRAMEWORK, ("springboot", "spring"), parent="Java"),
    SeedSkill("Ruby on Rails", FRAMEWORK, ("rails", "ror"), parent="Ruby"),
    SeedSkill("Laravel", FRAMEWORK, parent="PHP"),
    SeedSkill(".NET", FRAMEWORK, ("dotnet", "asp.net", "aspnet", ".net core"), parent="C#"),
    SeedSkill("GraphQL", FRAMEWORK),
    SeedSkill("gRPC", FRAMEWORK),
    SeedSkill("REST API", PRACTICE, ("rest", "restful", "rest apis", "restful api")),
    SeedSkill("WebSockets", PRACTICE, ("websocket", "web sockets")),
    SeedSkill("Microservices", PRACTICE, ("microservice", "micro services")),
    # ---------------------------------------------------------------- databases
    SeedSkill("PostgreSQL", DATABASE, ("postgres", "psql", "pg", "postgre sql")),
    SeedSkill("MySQL", DATABASE, ("my sql",)),
    SeedSkill("SQLite", DATABASE),
    SeedSkill("MongoDB", DATABASE, ("mongo",)),
    SeedSkill("Redis", DATABASE),
    SeedSkill("Elasticsearch", DATABASE, ("elastic search", "elastic", "opensearch")),
    SeedSkill("Cassandra", DATABASE, ("apache cassandra",)),
    SeedSkill("DynamoDB", DATABASE, ("dynamo db",)),
    SeedSkill("Oracle Database", DATABASE, ("oracle db", "oracle sql", "plsql", "pl sql")),
    SeedSkill("Microsoft SQL Server", DATABASE, ("sql server", "mssql", "t sql", "tsql")),
    SeedSkill("Neo4j", DATABASE),
    SeedSkill("pgvector", DATABASE, ("pg vector",), parent="PostgreSQL"),
    SeedSkill("Pinecone", DATABASE),
    # ---------------------------------------------------------------- cloud & devops
    SeedSkill("AWS", CLOUD, ("amazon web services",)),
    SeedSkill("Google Cloud Platform", CLOUD, ("gcp", "google cloud")),
    SeedSkill("Microsoft Azure", CLOUD, ("azure",)),
    SeedSkill("Docker", TOOL, ("containerization", "containerisation")),
    SeedSkill("Kubernetes", TOOL, ("k8s", "kube")),
    SeedSkill("Terraform", TOOL, ("hcl",)),
    SeedSkill("Ansible", TOOL),
    SeedSkill("Jenkins", TOOL),
    SeedSkill("GitHub Actions", TOOL, ("github action",)),
    SeedSkill("GitLab CI", TOOL, ("gitlab ci cd",)),
    SeedSkill("CI/CD", PRACTICE, ("ci cd", "continuous integration", "continuous deployment")),
    SeedSkill("Nginx", TOOL),
    SeedSkill("Linux", TOOL, ("ubuntu", "debian", "centos", "unix")),
    SeedSkill("Prometheus", TOOL),
    SeedSkill("Grafana", TOOL),
    SeedSkill("Cloud Run", CLOUD, ("google cloud run",), parent="Google Cloud Platform"),
    SeedSkill("Lambda", CLOUD, ("aws lambda", "serverless"), parent="AWS"),
    SeedSkill("S3", CLOUD, ("amazon s3",), parent="AWS"),
    SeedSkill("EC2", CLOUD, ("amazon ec2",), parent="AWS"),
    # ---------------------------------------------------------------- data & messaging
    SeedSkill("Apache Kafka", TOOL, ("kafka",)),
    SeedSkill("RabbitMQ", TOOL, ("rabbit mq",)),
    SeedSkill("Apache Spark", TOOL, ("spark", "pyspark")),
    SeedSkill("Apache Airflow", TOOL, ("airflow",)),
    SeedSkill("Hadoop", TOOL),
    SeedSkill("dbt", TOOL, ("data build tool",)),
    SeedSkill("ETL", PRACTICE, ("elt", "data pipeline", "data pipelines")),
    SeedSkill("Pub/Sub", TOOL, ("pubsub", "google pub sub")),
    # ---------------------------------------------------------------- ml & ai
    SeedSkill("Machine Learning", PRACTICE, ("ml",)),
    SeedSkill("Deep Learning", PRACTICE, ("dl", "neural networks"), parent="Machine Learning"),
    SeedSkill("Natural Language Processing", PRACTICE, ("nlp",), parent="Machine Learning"),
    SeedSkill("Computer Vision", PRACTICE, ("cv",), parent="Machine Learning"),
    SeedSkill("PyTorch", FRAMEWORK, ("torch",), parent="Python"),
    SeedSkill("TensorFlow", FRAMEWORK, ("tensor flow",), parent="Python"),
    SeedSkill("Keras", FRAMEWORK, parent="TensorFlow"),
    SeedSkill("scikit-learn", FRAMEWORK, ("sklearn", "scikit learn"), parent="Python"),
    SeedSkill("Pandas", FRAMEWORK, parent="Python"),
    SeedSkill("NumPy", FRAMEWORK, ("numpy",), parent="Python"),
    SeedSkill("spaCy", FRAMEWORK, ("spacy",), parent="Python"),
    SeedSkill("Hugging Face", FRAMEWORK, ("huggingface", "transformers")),
    SeedSkill("LangChain", FRAMEWORK, ("lang chain",)),
    SeedSkill("OpenAI API", TOOL, ("openai", "gpt", "chatgpt api")),
    SeedSkill("Large Language Models", PRACTICE, ("llm", "llms")),
    SeedSkill("Embeddings", PRACTICE, ("vector embeddings", "sentence transformers")),
    SeedSkill("RAG", PRACTICE, ("retrieval augmented generation",)),
    SeedSkill("Recommendation Systems", PRACTICE, ("recommender systems", "recsys")),
    # ---------------------------------------------------------------- mobile
    SeedSkill("React Native", FRAMEWORK, ("reactnative",), parent="React"),
    SeedSkill("Flutter", FRAMEWORK, parent="Dart"),
    SeedSkill("Android", FRAMEWORK, ("android development",)),
    SeedSkill("iOS", FRAMEWORK, ("ios development",)),
    # ---------------------------------------------------------------- tools & practices
    # "github"/"gitlab" are no longer aliases here — they are skills in their
    # own right below. Candidates list them separately, and folding them in
    # made "Git, GitHub" collapse to a single entry.
    SeedSkill("Git", TOOL, ("version control",)),
    SeedSkill("Jira", TOOL),
    SeedSkill("Agile", PRACTICE, ("scrum", "kanban", "agile methodology")),
    SeedSkill("Test-Driven Development", PRACTICE, ("tdd",)),
    SeedSkill("Unit Testing", PRACTICE, ("unit tests",)),
    SeedSkill("Pytest", TOOL, parent="Python"),
    SeedSkill("Jest", TOOL, parent="JavaScript"),
    SeedSkill("Selenium", TOOL),
    SeedSkill("Cypress", TOOL),
    SeedSkill("Postman", TOOL),
    SeedSkill("Figma", TOOL),
    SeedSkill("System Design", PRACTICE, ("distributed systems", "software architecture")),
    SeedSkill(
        "Data Structures",
        PRACTICE,
        # "&" is stripped by normalisation, so the ampersand form has to be
        # listed in its normalised shape as well as spelled out.
        ("dsa", "data structures and algorithms", "data structures algorithms"),
    ),
    SeedSkill("Algorithms", PRACTICE),
    # "oops" is how it is almost always written on Indian CS resumes, and it
    # normalises differently from "oop" so it needs to be listed explicitly.
    SeedSkill(
        "Object-Oriented Programming",
        PRACTICE,
        ("oop", "oops", "oop concepts", "oops concepts", "object oriented programming"),
    ),
    SeedSkill("Design Patterns", PRACTICE),
    SeedSkill("Code Review", PRACTICE, ("code reviews",)),
    SeedSkill("Security", PRACTICE, ("application security", "appsec", "cybersecurity")),
    SeedSkill("OAuth", PRACTICE, ("oauth2", "oauth 2.0")),
    SeedSkill("JWT", PRACTICE, ("json web token", "json web tokens")),
    # ---------------------------------------------------------------- analytics
    SeedSkill("Tableau", TOOL),
    SeedSkill("Power BI", TOOL, ("powerbi",)),
    SeedSkill("Excel", TOOL, ("microsoft excel", "ms excel", "advanced excel")),
    SeedSkill("Data Analysis", PRACTICE, ("data analytics",)),
    SeedSkill("Data Visualization", PRACTICE, ("data visualisation",)),
    SeedSkill("Statistics", PRACTICE, ("statistical analysis",)),
    SeedSkill("A/B Testing", PRACTICE, ("ab testing", "split testing")),
    # ---------------------------------------------------------------- managed services & SaaS
    # Modern projects lean heavily on hosted services. Omitting them meant real
    # resumes listing Clerk, Inngest and Cloudinary matched nothing at all.
    SeedSkill("Clerk", TOOL, ("clerk auth", "clerk dev")),
    SeedSkill("Inngest", TOOL),
    SeedSkill("Cloudinary", TOOL),
    SeedSkill("Vercel", CLOUD),
    SeedSkill("Netlify", CLOUD),
    SeedSkill("Supabase", DATABASE),
    SeedSkill("Firebase", CLOUD, ("firestore",)),
    SeedSkill("Appwrite", CLOUD),
    SeedSkill("Railway", CLOUD),
    SeedSkill("Render", CLOUD),
    SeedSkill("Stripe", TOOL),
    SeedSkill("Razorpay", TOOL),
    SeedSkill("Auth0", TOOL),
    SeedSkill("Twilio", TOOL),
    SeedSkill("SendGrid", TOOL),
    SeedSkill("Resend", TOOL),
    SeedSkill("Cloudflare", CLOUD),
    SeedSkill("Prisma", FRAMEWORK, ("prisma orm",)),
    SeedSkill("Drizzle", FRAMEWORK, ("drizzle orm",)),
    SeedSkill("Mongoose", FRAMEWORK, parent="MongoDB"),
    SeedSkill("SQLAlchemy", FRAMEWORK, parent="Python"),
    SeedSkill("Socket.IO", FRAMEWORK, ("socketio", "socket io")),
    SeedSkill("Celery", FRAMEWORK, parent="Python"),
    SeedSkill("Streamlit", FRAMEWORK, parent="Python"),
    SeedSkill("Gradio", FRAMEWORK, parent="Python"),

    # ---------------------------------------------------------------- developer tools
    # GitHub is its own entry rather than a Git alias: candidates list them
    # separately, and a portfolio on GitHub is a distinct signal from knowing
    # version control.
    SeedSkill("GitHub", TOOL, ("github profile",)),
    SeedSkill("GitLab", TOOL),
    SeedSkill("Bitbucket", TOOL),
    SeedSkill("VS Code", TOOL, ("visual studio code", "vscode")),
    SeedSkill("Visual Studio", TOOL),
    SeedSkill("IntelliJ IDEA", TOOL, ("intellij",)),
    SeedSkill("PyCharm", TOOL),
    SeedSkill("Eclipse", TOOL),
    SeedSkill("Jupyter Notebook", TOOL, ("jupyter", "jupyter notebooks", "ipython notebook")),
    SeedSkill("Google Colab", TOOL, ("colab", "colaboratory", "google colaboratory")),
    SeedSkill("Anaconda", TOOL, ("conda",)),
    SeedSkill("Kaggle", TOOL),
    SeedSkill("LeetCode", TOOL, ("leet code",)),
    SeedSkill("CodeChef", TOOL, ("code chef",)),
    SeedSkill("HackerRank", TOOL, ("hacker rank",)),
    SeedSkill("Codeforces", TOOL, ("code forces",)),
    SeedSkill("Notion", TOOL),
    SeedSkill("Slack", TOOL),
    SeedSkill("Trello", TOOL),
    SeedSkill("Confluence", TOOL),

    # ---------------------------------------------------------------- cs fundamentals
    # Coursework lines are near-universal on student resumes and were matching
    # nothing.
    SeedSkill("DBMS", PRACTICE, ("database management systems", "database management system")),
    SeedSkill("Operating Systems", PRACTICE, ("os", "operating system")),
    SeedSkill("Computer Networks", PRACTICE, ("networking", "computer networking")),
    SeedSkill("Compiler Design", PRACTICE, ("compilers",)),
    SeedSkill("Software Engineering", PRACTICE, ("sdlc",)),
    SeedSkill("Theory of Computation", PRACTICE, ("automata theory", "toc")),
    SeedSkill("Computer Architecture", PRACTICE, ("coa", "computer organization")),
    SeedSkill("Discrete Mathematics", PRACTICE, ("discrete maths",)),
    SeedSkill("Linear Algebra", PRACTICE),
    SeedSkill("Probability", PRACTICE, ("probability and statistics",)),
    SeedSkill("Competitive Programming", PRACTICE, ("cp",)),

    # ---------------------------------------------------------------- ml architectures
    # A resume naming CNN or ConvLSTM is describing real, specific work; the
    # taxonomy only knew the umbrella terms.
    SeedSkill("CNN", PRACTICE, ("convolutional neural network", "convolutional neural networks"),
              parent="Deep Learning"),
    SeedSkill("RNN", PRACTICE, ("recurrent neural network", "recurrent neural networks"),
              parent="Deep Learning"),
    SeedSkill("LSTM", PRACTICE, ("long short term memory",), parent="Deep Learning"),
    SeedSkill("ConvLSTM", PRACTICE, ("bi-directional convlstm", "bidirectional convlstm",
                                     "conv lstm"), parent="LSTM"),
    SeedSkill("Transformers", PRACTICE, ("transformer architecture",), parent="Deep Learning"),
    SeedSkill("BERT", PRACTICE, parent="Transformers"),
    SeedSkill("GAN", PRACTICE, ("generative adversarial network", "gans"),
              parent="Deep Learning"),
    SeedSkill("YOLO", PRACTICE, ("you only look once",), parent="Computer Vision"),
    SeedSkill("OpenCV", FRAMEWORK, ("cv2",), parent="Computer Vision"),
    SeedSkill("Generative AI", PRACTICE, ("gen ai", "genai", "generative artificial intelligence")),
    SeedSkill("Prompt Engineering", PRACTICE),
    SeedSkill("Fine-tuning", PRACTICE, ("finetuning", "model fine tuning")),
    SeedSkill("Matplotlib", FRAMEWORK, parent="Python"),
    SeedSkill("Seaborn", FRAMEWORK, parent="Python"),
    SeedSkill("Plotly", FRAMEWORK),
    SeedSkill("NLTK", FRAMEWORK, parent="Natural Language Processing"),
    SeedSkill("XGBoost", FRAMEWORK, parent="Machine Learning"),
    SeedSkill("Feature Engineering", PRACTICE, parent="Machine Learning"),
    SeedSkill("Model Evaluation", PRACTICE, ("model validation",), parent="Machine Learning"),

    # ---------------------------------------------------------------- office
    SeedSkill("Microsoft Word", TOOL, ("ms word", "msword")),
    SeedSkill("Microsoft PowerPoint", TOOL, ("ms powerpoint", "powerpoint", "ms power point")),
    SeedSkill("Microsoft Office", TOOL, ("ms office",)),
    SeedSkill("Google Workspace", TOOL, ("google sheets", "google docs", "g suite")),
    SeedSkill("LaTeX", TOOL),

    # ---------------------------------------------------------------- soft skills
    SeedSkill("Communication", SOFT, ("verbal communication", "written communication")),
    SeedSkill("Leadership", SOFT, ("team leadership",)),
    SeedSkill("Teamwork", SOFT, ("collaboration", "team player")),
    SeedSkill("Problem Solving", SOFT, ("problem-solving", "analytical thinking")),
    SeedSkill("Mentoring", SOFT, ("mentorship", "coaching")),
    SeedSkill("Project Management", SOFT),
    SeedSkill("Time Management", SOFT),
    SeedSkill("Critical Thinking", SOFT),
    SeedSkill("Adaptability", SOFT, ("flexibility",)),
    SeedSkill("Stakeholder Management", SOFT),
)


def seed_skill_count() -> int:
    return len(SEED_SKILLS)
