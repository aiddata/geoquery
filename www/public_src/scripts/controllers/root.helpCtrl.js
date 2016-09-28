angular.module('aiddataDET')
.controller('HelpCtrl', function($scope, $rootScope, $log, $sce, info) {
  $scope.content = _.each(info.help, function(qa) {
    qa.question_trusted = $sce.trustAsHtml(qa.question);
    qa.answer_trusted = $sce.trustAsHtml(qa.answer);
  });
});
