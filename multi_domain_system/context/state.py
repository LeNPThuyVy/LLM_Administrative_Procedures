from copy import deepcopy


def create_initial_context():
    return {
        "recent_messages": [],
        "structured_context": {},
        "summary": ""
    }


def extract_simple_context(message, context):
    text = message.lower()

    locations = [
        "tp.hcm",
        "hồ chí minh",
        "hà nội",
        "đà nẵng",
        "quận 1",
        "quận 3"
    ]

    for location in locations:
        if location in text:
            context["structured_context"]["location"] = location

    return context


def update_context_before_query(context, user_message):

    if context is None:
        context = create_initial_context()

    new_context = deepcopy(context)

    new_context["recent_messages"].append({
        "role": "user",
        "content": user_message
    })

    new_context["recent_messages"] = (
        new_context["recent_messages"][-10:]
    )

    new_context = extract_simple_context(
        user_message,
        new_context
    )

    return new_context


def update_context_after_answer(context, answer):

    new_context = deepcopy(context)

    new_context["recent_messages"].append({
        "role": "assistant",
        "content": answer
    })

    new_context["recent_messages"] = (
        new_context["recent_messages"][-10:]
    )

    return new_context