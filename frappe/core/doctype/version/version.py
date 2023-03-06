# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import json

import frappe
from frappe.model import no_value_fields, table_fields
from frappe.model.document import Document
from frappe.model.db_query import get_doctype_title


class Version(Document):
	def update_version_info(self, old: Document | None, new: Document) -> bool:
		"""Update changed info and return true if change contains useful data."""
		if not old:
			# Check if doc has some information about creation source like data import
			return self.for_insert(new)
		else:
			return self.set_diff(old, new)

	def set_diff(self, old: Document, new: Document) -> bool:
		"""Set the data property with the diff of the docs if present"""
		diff = get_diff(old, new)
		if diff:
			self.ref_doctype = new.doctype
			self.docname = new.name
			self.data = frappe.as_json(diff, indent=None, separators=(",", ":"))
			if self.ref_doctype == "Work Item":
				#field change
				if diff.changed:
					for row in diff.changed:
						self.append("version_detail",{"field_name":row[0],"original_value":diff[row[0]][0],"new_value":diff[row[0]][1],"hash_original_value":row[1],"hash_new_value":row[2]})
				
				#table or tablemulti select
				if diff.added or diff.removed:
					for row_added in diff.added:
						doc = frappe.get_meta(row_added[1]['doctype'])
						for field in doc.fields:
							if field.fieldname in row_added[1].keys():
								if field.fieldtype == "Link":
									title_field = get_doctype_title(field.options)
									title_value = frappe.db.get_value(field.options , row_added[1][field.fieldname] , title_field)
									self.append("version_detail",{"is_table":1,"table_field":field.fieldname,"field_name":row_added[0],"new_value":title_value,"hash_new_value":row_added[1][field.fieldname]})
								else:
									self.append("version_detail",{"is_table":1,"table_field":field.fieldname,"field_name":row_added[0],"new_value":row_added[1][field.fieldname],"hash_new_value":row_added[1][field.fieldname]})
					

					for row_added in diff.removed:
						doc = frappe.get_meta(row_added[1]['doctype'])
						for field in doc.fields:
							if field.fieldname in row_added[1].keys():
								if field.fieldtype == "Link":
									title_field = get_doctype_title(field.options)
									title_value = frappe.db.get_value(field.options , row_added[1][field.fieldname] , title_field)
									self.append("version_detail",{"is_table":1,"table_field":field.fieldname,"field_name":row_added[0],"original_value":title_value,"hash_original_value":row_added[1][field.fieldname]})
								else:
									self.append("version_detail",{"is_table":1,"table_field":field.fieldname,"field_name":row_added[0],"original_value":row_added[1][field.fieldname],"hash_original_value":row_added[1][field.fieldname]})

				#table row change
				if diff.row_changed:
					for row_added in diff.row_changed:
						field = frappe.get_meta(frappe.get_meta("Work Item").get_field(row_added[0]).options).get_field(row_added[3][0][0])
						if field.fieldtype == "Link":
							if field.options == "User":
								self.append("version_detail",{"is_table":1,"table_field":row_added[0],"field_name":row_added[3][0][0],"original_value":row_added[3][0][1],"new_value":row_added[3][0][2],"hash_original_value":frappe.db.get_value("User", {"full_name":row_added[3][0][1]},"name"),"hash_new_value":frappe.db.get_value("User", {"full_name":row_added[3][0][2]},"name")})
							else:
								title_field = get_doctype_title(field.options)
								self.append("version_detail",{"is_table":1,"table_field":row_added[0],"field_name":row_added[3][0][0],"original_value":row_added[3][0][1],"new_value":row_added[3][0][2],"hash_original_value":frappe.db.get_value(field.options , row_added[3][0][1] , title_field),"hash_new_value":frappe.db.get_value(field.options , row_added[3][0][2] , title_field)})
						else:
							self.append("version_detail",{"is_table":1,"table_field":row_added[0],"field_name":row_added[3][0][0],"original_value":row_added[3][0][1],"new_value":row_added[3][0][2],"hash_original_value":row_added[3][0][1],"hash_new_value":row_added[3][0][2]})

	
			return True
		else:
			return False

	def for_insert(self, doc: Document) -> bool:
		updater_reference = doc.flags.updater_reference
		if not updater_reference:
			return False

		data = {
			"creation": doc.creation,
			"updater_reference": updater_reference,
			"created_by": frappe.db.get_value("User", doc.owner,"full_name")
		}
		self.ref_doctype = doc.doctype
		self.docname = doc.name
		self.data = frappe.as_json(data, indent=None, separators=(",", ":"))
		return True

	def get_data(self):
		return json.loads(self.data)


def get_diff(old, new, for_child=False):
	"""Get diff between 2 document objects

	If there is a change, then returns a dict like:

	        {
	                "changed"    : [[fieldname1, old, new], [fieldname2, old, new]],
	                "added"      : [[table_fieldname1, {dict}], ],
	                "removed"    : [[table_fieldname1, {dict}], ],
	                "row_changed": [[table_fieldname1, row_name1, row_index,
	                        [[child_fieldname1, old, new],
	                        [child_fieldname2, old, new]], ]
	                ],

	        }"""
	if not new:
		return None

	blacklisted_fields = ["Markdown Editor", "Text Editor", "Code", "HTML Editor"]

	# capture data import if set
	data_import = new.flags.via_data_import
	updater_reference = new.flags.updater_reference

	out = frappe._dict(
		changed=[],
		added=[],
		removed=[],
		row_changed=[],
		data_import=data_import,
		updater_reference=updater_reference,
	)

	for df in new.meta.fields:
		if df.fieldtype in no_value_fields and df.fieldtype not in table_fields:
			continue

		old_value, new_value = old.get(df.fieldname), new.get(df.fieldname)

		if df.fieldtype in table_fields:
			# make maps
			old_row_by_name, new_row_by_name = {}, {}
			for d in old_value:
				old_row_by_name[d.name] = d
			for d in new_value:
				new_row_by_name[d.name] = d

			# check rows for additions, changes
			for i, d in enumerate(new_value):
				if d.name in old_row_by_name:
					diff = get_diff(old_row_by_name[d.name], d, for_child=True)
					if diff and diff.changed:
						out.row_changed.append((df.fieldname, i, d.name, diff.changed))
				else:
					out.added.append([df.fieldname, d.as_dict()])

			# check for deletions
			for d in old_value:
				if not d.name in new_row_by_name:
					out.removed.append([df.fieldname, d.as_dict()])

		elif old_value != new_value:
			if df.fieldtype not in blacklisted_fields:
				old_value = old.get_formatted(df.fieldname) if old_value else old_value
				new_value = new.get_formatted(df.fieldname) if new_value else new_value

			if df.fieldtype == "Link" and df.options == "User":
				old_value = frappe.db.get_value("User", old_value,"full_name") or old_value
				new_value = frappe.db.get_value("User", new_value ,"full_name") or new_value

			if not old_value:
				old_value = 'Not Specified'

			if old_value != new_value:
				out.changed.append((df.fieldname, old_value, new_value))

			old_value_title = old_value
			new_value_title = new_value

			if df.fieldtype == "Link" and df.fieldname != "User":
				title_field = get_doctype_title(df.options)
				old_value_title = frappe.db.get_value(df.options , old_value , title_field) or old_value
				if not old_value:
					old_value_title = 'Not Specified'
				new_value_title = frappe.db.get_value(df.options , new_value , title_field) or new_value

			if old_value_title != new_value_title:
				out[df.fieldname] = [old_value_title, new_value_title]

	# docstatus
	if not for_child and old.docstatus != new.docstatus:
		out.changed.append(["docstatus", old.docstatus, new.docstatus])

	if any((out.changed, out.added, out.removed, out.row_changed)):
		return out

	else:
		return None


def on_doctype_update():
	frappe.db.add_index("Version", ["ref_doctype", "docname"])
