### check: run code quality tools for both parts                                                 
FROM python:3.14-rc-slim AS check                                                                
WORKDIR /src                                                                                     
                                                                                                
RUN apt-get update && apt-get install -y curl && \                                               
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \                               
    apt-get install -y nodejs && \                                                               
    rm -rf /var/lib/apt/lists/*
                                                                                                
COPY int/ /src/int/
WORKDIR /src/int
RUN pip install --no-cache-dir -e . \                                                            
    && pip install --no-cache-dir --group dev \
    && ln -s "$(which ruff)" /src/int/ruff \                                                     
    && ln -s "$(which mypy)" /src/int/mypy
                                                                                                
RUN ./ruff check src && ./ruff format --check src
RUN ./mypy src                                                                                   
                
COPY tester/ /src/tester/
RUN cd /src/tester && npm ci \
    && ln -s /src/tester/node_modules/.bin/eslint /src/tester/eslint \                           
    && ln -s /src/tester/node_modules/.bin/prettier /src/tester/prettier
RUN cd /src/tester && ./eslint "src/**/*.ts" && ./prettier --check "src/**/*.ts"

ENTRYPOINT ["/bin/bash"]

### build-test: compile TypeScript tester                                                        
FROM check AS build-test
RUN cd /src/tester && npm run build                                                              
                
### runtime: interpreter only, no dev tools
FROM python:3.14-rc-slim AS runtime
WORKDIR /src/int
COPY int/src/ /src/int/src/                                                                      
RUN pip install --no-cache-dir pydantic~=2.12.5 "pydantic-xml[lxml]~=2.19.0" types-lxml
ENTRYPOINT ["python3", "/src/int/src/solint.py"]

### test: runtime + compiled tester
FROM runtime AS test                                                                             
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*                                                                  
COPY --from=build-test /src/tester/dist/ /src/tester/dist/
COPY --from=build-test /src/tester/node_modules/ /src/tester/node_modules/                       
COPY tester/package.json /src/tester/package.json 
ENTRYPOINT ["node", "/src/tester/dist/tester.js", "--interpreter", "python3 /src/int/src/solint.py"]