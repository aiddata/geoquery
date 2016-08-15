angular.module('aiddataDET')
.controller('OptionsCtrl', function ($scope, $rootScope, $log, $stateParams, queryFactory) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: 'Extract Options',
      type: 'checkbox',
      loc: 'options.extract_types',
      dest: 'options.extract_types',
      pick: function(x) { return _.get(x, 'name'); },
      data: []
    },
    {
      name: 'Years',
      type: 'checkbox',
      loc: 'resources',
      dest: 'files',
      pick: function(x) { return _.pick(x, ['name', 'path']); },
      data: []
    }
  ];

  $scope.toggleOption = function (isChecked, val, option) {
    var optionData = option.pick(val);

    var action = isChecked ? queryFactory.toggleOptionOn(option.dest, optionData) :
      queryFactory.toggleOptionOff(option.dest, optionData);

    var direction = val.checked ? 'off' : 'on';

    $rootScope.$broadcast('options:updated', { key: option.dest, value: optionData, direction: direction });
  };

  $scope.getTimeStamp = function (date, format) {
    var timeFormatter = d3.timeFormat('%Y');
    var timeParser = d3.timeParse(format),
        formDate = timeFormatter(timeParser(date));
    return formDate;
  };

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.dataset = queryFactory.getDataset($stateParams.dataset);

    _.each($scope.options, function (opt) {
      mapOption(opt);
    });
  });


  $rootScope.$on('dataset:selected', function (e, data) {
    $scope.dataset = data;
  });

  $rootScope.$on('options:updated', function(e, data) {
    var search = _.isString(data.value) ? { name: data.value } : data.value;
    var targetOption = _.chain($scope.options)
      .find({ dest: data.key })
      .get('data')
      .find(search)
      .value();

    targetOption.checked = data.direction === 'on';
  });

  function mapOption (option) {
    option.data = _.chain($scope.dataset)
      .get(option.loc)
      .map(function (choice) {
        return _.isString(choice) ? { name: choice } : choice;
      })
      .value();
  }
});
