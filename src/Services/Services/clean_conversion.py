############# Services/Services/clean_conversion.py #############




from typing import Optional, Type, List, Union
import asyncio
import loguru
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate

from LLM.Generation.generation_factory import GenerationFactory, GenerationConfig
from ..service_interface import ServiceInterface
from ..Exceptions.clean_conversion_exc import CleanConversionException
from DatabaseInfrastructure.Mongodb.async_dml import MongoDML
from DatabaseInfrastructure.Mongodb.async_connection import MongoConnectionManager

class TurnConversionsToJson(ServiceInterface):
    FAILED_COLLECTION = "falied_cleaned_jsons"
    SUCCESS_COLLECTION = "cleaned_jsons"

    def __init__(
        self,
        mongo_connection: MongoConnectionManager,
        generation_config: GenerationConfig,
        extraction_schema: Type[BaseModel],
        logger: Optional[loguru.Logger] = None,
    ):
        self.mongo_connection:MongoConnectionManager=mongo_connection
        self.mongo:MongoDML = None
        self.generation_config = generation_config
        self.logger = logger or loguru.logger
        self.extraction_schema = extraction_schema

        self.model: Optional[GenerationFactory] = None
        self.structured_llm = None

    @classmethod
    def init_service(
        cls,
        mongo: MongoController,
        generation_config: GenerationConfig,
        extraction_schema: Type[BaseModel],
        logger: Optional[loguru.Logger] = None,
    ):
        logger = logger or loguru.logger
        logger.info("Initializing the turning into JSON service")

        return cls(
            mongo=mongo,
            generation_config=generation_config,
            extraction_schema=extraction_schema,
            logger=logger,
        )

    async def start_model(self):
        if not self.model:
            self.model = await GenerationFactory.create_llm(
                model_config=self.generation_config,
            )

        if not self.structured_llm:
            self.structured_llm = self.model.with_structured_output(self.extraction_schema)


    async def jsonify(self, text: str) -> BaseModel:
        await self.start_model()

        try:
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You extract structured conversation data from chat text and return it using the provided schema.",
                    ),
                    (
                        "human",
                        """Convert the following text into structured conversation data.

    Extract:
    - file_id
    - file_type
    - sender_role (client or agent)
    - sender_name
    - message
    - message_datetime (ISO 8601)

    Rules:
    - Use one message object per chat turn.
    - Do not split a single turn into client/agent fields.
    - Preserve chronological order.
    - If a field is missing, use null.

    Text:
    {text}
    """,
                    ),
                ]
            )

            chain = prompt | self.structured_llm
            response_document = await chain.ainvoke({"text": text})

            await self._upload(response_document)
            return response_document

        except Exception as e:
            self.logger.exception("Error in jsonify")
            await self._upload_failed(text=text, error=e)
            raise TurnConversionsToJsonException(message=str(e))

    async def jsonify_multiple_texts(
        self,
        texts: List[str],
        max_workers: int = 5,
    ) -> List[BaseModel]:
        await self.start_model()

        semaphore = asyncio.Semaphore(max_workers)

        async def worker(text: str):
            async with semaphore:
                try:
                    return await self.jsonify(text)
                except Exception as e:
                    # Return the exception + the original text so we can track it
                    return {"error": e, "text": text}

        tasks = [worker(text) for text in texts]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful_results: List[BaseModel] = []

        for result in results:
            if isinstance(result, Exception):
                # Safety net: unexpected exception that escaped the worker
                self.logger.error(f"A text failed during batch processing: {result}")
            elif isinstance(result, dict) and "error" in result:
                self.logger.error(
                    f"A text failed during batch processing: {result['error']}"
                )
                # Already uploaded to 'failed' inside jsonify(), nothing more to do
            else:
                successful_results.append(result)

        return successful_results

    async def _upload(self, response_document: BaseModel):
        try:
            if not self.mongo:
                raise ValueError("Mongo controller was not provided.")

            document_dict = response_document.model_dump()
            await self.mongo.insert_one(
                collection_name=self.SUCCESS_COLLECTION,
                document=document_dict,
            )
            return True

        except Exception as e:
            self.logger.exception("Error uploading to DB")
            raise TurnConversionsToJsonException(message=str(e))

    async def _upload_failed(self, text: str, error: Exception):
        """
        Store any text that failed during LLM conversion or upload
        into the 'failed' Mongo collection for later inspection / retry.
        """
        try:
            if not self.mongo:
                self.logger.error(
                    "Mongo controller not provided, cannot record failed text."
                )
                return False

            failed_document = {
                "text": text,
                "error_type": type(error).__name__,
                "error_message": str(error),
            }

            await self.mongo.insert_one(
                collection_name=self.FAILED_COLLECTION,
                document=failed_document,
            )
            return True

        except Exception as e:
            # We don't want a failure-logging failure to crash the whole pipeline
            self.logger.exception(f"Error uploading FAILED record to DB: {e}")
            return False

    async def run(
        self, text: Union[str, List[str]]
    ) -> Union[BaseModel, List[BaseModel]]:
        await self.start_model()

        if isinstance(text, list):
            return await self.jsonify_multiple_texts(text)

        return await self.jsonify(text)

    

    