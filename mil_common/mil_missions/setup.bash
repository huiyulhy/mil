# Missions
alias runmission="rosrun mil_missions mission_client run"
alias cancelmission="rosrun mil_missions mission_client cancel"
alias listmissions="rosrun mil_missions mission_client list"
_mission_complete() {
	local MISSION

	# Iterate over the comma diliniated list of known alarms
	for MISSION in $(rosparam get /available_missions | grep -oh "[A-Za-z0-9_ ]*"); do
		# Skip any entry that does not match the string to complete
		if [[ -z "$2" || ! -z "$(echo ${MISSION:0:${#2}} | grep $2)" ]]; then
				COMPREPLY+=( "$MISSION" )
		fi
	done
}


# Registers the autocompletion function to be invoked for ros_connect
complete -F _mission_complete runmission
