import os, json
from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag
def action_url(url_name, *args):
    return reverse(url_name, args=args)

@register.filter(name='format_amount')
def format_amount(value):
    try:
        value = float(value)

        return "${:,.2f}".format(value)
    except:
        return value
    
@register.filter(name='format_money')
def format_money(value):
    value = float(value)

    return "${:,.2f}".format(value)

@register.filter
def pretty_list(value):
    return '<br>'.join(value)

@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    '''
    Returns the URL-encoded querystring for the current page,
    updating the params with the key/value pairs passed to the tag.
    
    E.g: given the querystring ?foo=1&bar=2
    {% query_transform bar=3 %} outputs ?foo=1&bar=3
    {% query_transform foo='baz' %} outputs ?foo=baz&bar=2
    {% query_transform foo='one' bar='two' baz=99 %} outputs ?foo=one&bar=two&baz=99
    
    A RequestContext is required for access to the current querystring.
    '''
    query = context['request'].GET.copy()
    for k, v in kwargs.items():
        query[k] = v
    return query.urlencode()

@register.filter
def pretty_json(value):
    return json.dumps(value, indent=4)

@register.filter
def load_and_pretty_json(value):
    try:
        if type(value) == str:
            return json.dumps(json.loads(value), indent=4)
        return json.dumps(value, indent=4)
    except Exception as e:
        print(e)
        return value

@register.filter
def list_index(indexable, i):
    return indexable[i]

@register.simple_tag(takes_context=True)
def open_seats(context, obj):
    open_seats = obj.max_enrollment - obj.enrollment

    return open_seats

@register.filter(name='times') 
def times(number):
    return range(number)

@register.filter
def getfilename(value):
    # Use .name (the stored path) — NOT .file, which opens the underlying file
    # and raises FileNotFoundError when it is missing from storage. Fail quietly
    # (empty string) for a missing/blank file rather than 500-ing the page.
    try:
        return os.path.basename(getattr(value, 'name', value) or '')
    except Exception:
        return ''

@register.filter(name='dict_key')
def dict_key(d, k):
    '''Returns the given key from a dictionary.'''
    return d[k]

@register.filter(name='format_amount')
def format_amount(value):
    value = float(value)

    return "${:,.2f}".format(value)


@register.filter(name='highlight_ifinlist')
def highlight_ifinlist(value, items):
    return 'highlight-interest' if value in items else ''

@register.filter(name='highlight_iftaken')
def highlight_iftaken(value, items):
    return 'highlight-taken' if f'{value.name}' in items else '123'

@register.filter(name='highlight_ifinhs')
def highlight_ifinhs(value, items):
    return 'highlight-in-hs' if f'{value}' in items else '123'

@register.filter(name='toupper') 
def toupper(value):
    return value.upper()
