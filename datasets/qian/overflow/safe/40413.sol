pragma solidity ^0.4.25;


contract DaoChallenge {

	function withdrawEtherOrThrow(uint256 amount) {
		bool result = msg.sender.call.value(amount)();
		if (!result) { throw; }
	}
}