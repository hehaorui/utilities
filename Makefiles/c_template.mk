# Define required macros here
SHELL = 
CC = 
CFLAGS = -Wall -ggdb
INCLUDEFLAGS = 
SRCPATH = src
BINPATH = bin
BUILDPATH = build
DEPPATH = dep
OBJS = 
TARGET = 
vpath %.h ${SRCPATH}
vpath %.c ${SRCPATH}
vpath %.o ${BUILDPATH}
vpath ${TARGET} ${BUILDPATH}


.PHONY:ALL 
ALL: path ${TARGET} 

.PHONY: path
path:
	@find ./${DEPPATH} 1>/dev/null || (echo "mkdir ${DEPPATH}"; mkdir ${DEPPATH})
	@find ./${BUILDPATH} 1>/dev/null || (echo "mkdir ${BUILDPATH}"; mkdir ${BUILDPATH}) 

${TARGET}: ${OBJS}
	@set -e; \
	cd ${BUILDPATH}; \
	echo "${CC} -o ${notdir $@} ${CFLAGS} ${notdir $^}"; \
	${CC} -o ${notdir $@} ${CFLAGS} ${notdir $^}; \
	echo "Build Succeeded";
	
${OBJS}: %.o: %.c
	${CC} -o ${BUILDPATH}/$@ ${CFLAGS} -c $<

	
${DEPPATH}/%.d:  %.c
	@set -e; rm -f $@; \
  	$(CC) -MM $(CFLAGS) $< ${INCLUDEFLAGS} > $@.$$$$; \
	sed 's,\($*\)\.o[ :]*,\1.o $@ : ,g' < $@.$$$$ > $@; \
  	rm -f $@.$$$$

-include ${addprefix ${DEPPATH}/, ${OBJS:.o=.d}}

.PHONY: clean
clean:
	-rm -f ${BUILDPATH}/*.o ${DEPPATH}/*.d ${DEPPATH}/*.d.* ${BUILDPATH}/${TARGET}

